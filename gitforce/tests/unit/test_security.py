from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gitforce.app.database import models
from gitforce.app.database.session import engine
from gitforce.app.main import app
from gitforce.app.security.logging import JsonFormatter, SecretFilter
from gitforce.app.security.rate_limit import RateLimitMiddleware, TokenBucket
from gitforce.app.security.recovery import (
    TransientRetryPolicy,
    idempotency_store,
)
from gitforce.app.security.secrets import SecretManager


@pytest.fixture(autouse=True)
async def _db() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)
        await conn.run_sync(models.Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_token_bucket_allows_burst_then_throttles() -> None:
    bucket = TokenBucket(capacity=3, refill_per_second=0.01)
    assert bucket.take()
    assert bucket.take()
    assert bucket.take()
    assert not bucket.take()


def test_token_bucket_refills() -> None:
    bucket = TokenBucket(capacity=1, refill_per_second=1000.0)
    assert bucket.take()
    import time

    time.sleep(0.002)
    assert bucket.take()


def test_rate_limit_middleware_disabled_lets_through() -> None:
    mw = RateLimitMiddleware(app)
    assert mw._bucket_for("1.2.3.4", 2, 0.001).capacity == 2


async def test_secret_manager_registers_and_describes() -> None:
    manager = SecretManager()
    redactor = manager.register()
    # A configured secret value must be scrubbed once registered.
    sample = "looks-like-a-secret-value-123"
    assert sample not in redactor.redact(f"token={sample}")
    described = manager.describe()
    assert isinstance(described, dict)
    assert "GITHUB_TOKEN" in described


def test_json_formatter_outputs_structured_record() -> None:
    import json
    import logging

    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="gitforce.test",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.task_id = "t1"
    record.agent = "coder"
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "gitforce.test"
    assert payload["message"] == "hello"
    assert payload["task_id"] == "t1"
    assert payload["agent"] == "coder"
    assert "timestamp" in payload


def test_secret_filter_redacts() -> None:
    import logging

    filt = SecretFilter((r"super-secret-token",))
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="token=super-secret-token in logs",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record)
    assert "[REDACTED]" in record.getMessage()
    assert "super-secret-token" not in record.getMessage()


async def test_transient_retry_succeeds() -> None:
    import httpx

    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.TransportError("connection reset")
        return "ok"

    policy = TransientRetryPolicy(max_attempts=3, base_delay=0.01)
    result = await policy.run(flaky)
    assert result.ok
    assert result.value == "ok"
    assert result.attempts == 3


async def test_transient_retry_gives_up_after_attempts() -> None:
    import httpx

    attempts = {"n": 0}

    async def always_fail() -> str:
        attempts["n"] += 1
        raise httpx.ConnectError("down")

    policy = TransientRetryPolicy(max_attempts=2, base_delay=0.01)
    result = await policy.run(always_fail)
    assert not result.ok
    assert result.attempts == 2
    assert result.category == "TRANSIENT"


async def test_transient_retry_does_not_retry_permanent() -> None:
    from gitforce.app.llm.models import LLMResponseError

    attempts = {"n": 0}

    async def permanent() -> str:
        attempts["n"] += 1
        raise LLMResponseError("bad JSON")

    policy = TransientRetryPolicy(max_attempts=3, base_delay=0.01)
    result = await policy.run(permanent)
    assert not result.ok
    assert attempts["n"] == 1
    assert result.category == "PERMANENT"


def test_idempotency_key_deterministic() -> None:
    k1 = idempotency_store.key("op", "task1", "input")
    k2 = idempotency_store.key("op", "task1", "input")
    k3 = idempotency_store.key("op", "task1", "other")
    assert k1 == k2
    assert k1 != k3


def test_idempotency_check_and_mark() -> None:
    store = idempotency_store
    key = store.key("op", "task2")
    assert store.is_new(key)
    assert store.check_and_mark(key)
    assert not store.check_and_mark(key)
    assert not store.is_new(key)


async def test_health_with_rate_limit(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_rate_limit_middleware_returns_429() -> None:
    # Instantiate middleware with tight limits and drive it directly.
    mw = RateLimitMiddleware(app)
    mw._buckets.clear()

    from starlette.requests import Request
    from starlette.responses import PlainTextResponse


    # Override bucket behaviour: force a full bucket that refuses tokens.
    bucket = TokenBucket(capacity=1, refill_per_second=0.0001)
    mw._buckets["1.2.3.4"] = bucket
    bucket.take()  # consume the only token

    async def ok_route(request):
        return PlainTextResponse("ok")

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [],
        "client": ("1.2.3.4", 1234),
        "query_string": b"",
        "scheme": "http",
        "server": ("test", 80),
        "raw_path": b"/health",
        "root_path": "",
    }
    request = Request(scope)
    response = await mw.dispatch(request, ok_route)
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_git_auth_url_redacted_from_errors() -> None:
    from gitforce.app.github.git import _redact

    url = "https://x-access-token:ghp_Sup3rSecretToken123456789@github.com/org/repo"
    out = _redact(f"push failed: {url}")
    assert "ghp_Sup3rSecretToken123456789" not in out
    assert "[REDACTED]" in out


def _make_app_settings(tmp_path: Path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pem_path = tmp_path / "ghapp.pem"
    pem_path.write_bytes(private_key)

    from gitforce.app.config.settings import Settings

    return Settings(
        env="test",
        github_app_id="12345",
        github_app_private_key_path=str(pem_path),
        github_app_installation_id="67890",
        github_token="ghp_classic",
    )


async def test_github_app_auth_returns_installation_token(tmp_path: Path) -> None:
    import httpx

    from gitforce.app.github.app_auth import GitHubAppAuthenticator

    settings = _make_app_settings(tmp_path)
    auth = GitHubAppAuthenticator(settings)

    class _Fake(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request):
            assert request.url.path == "/app/installations/67890/access_tokens"
            assert "Authorization" in request.headers
            assert request.headers["Authorization"].startswith("Bearer ")
            return httpx.Response(
                201,
                json={
                    "token": "ghs_installation_token_123",
                    "expires_at": "2099-01-01T00:00:00Z",
                },
                request=request,
            )

    auth._http._transport = _Fake()  # noqa: SLF001
    token = await auth.get_token()
    assert token == "ghs_installation_token_123"
    await auth.aclose()


async def test_github_app_auth_caches_token(tmp_path: Path) -> None:
    import httpx

    from gitforce.app.github.app_auth import GitHubAppAuthenticator

    settings = _make_app_settings(tmp_path)
    auth = GitHubAppAuthenticator(settings)
    calls = {"n": 0}

    class _Fake(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request):
            calls["n"] += 1
            return httpx.Response(
                201,
                json={
                    "token": f"ghs_token_{calls['n']}",
                    "expires_at": "2099-01-01T00:00:00Z",
                },
                request=request,
            )

    auth._http._transport = _Fake()  # noqa: SLF001
    assert await auth.get_token() == "ghs_token_1"
    assert await auth.get_token() == "ghs_token_1"  # cached
    assert calls["n"] == 1
    await auth.aclose()


async def test_github_app_auth_falls_back_to_classic_token() -> None:
    from gitforce.app.config.settings import Settings
    from gitforce.app.github.app_auth import GitHubAppAuthenticator

    settings = Settings(env="test", github_token="ghp_classic")
    async with GitHubAppAuthenticator(settings) as auth:
        token = await auth.get_token()
    assert token == "ghp_classic"


def test_git_url_redaction_regex() -> None:
    from gitforce.app.github.git import _redact

    assert _redact("https://user:pass@github.com/org/repo") == (
        "https://[REDACTED]@github.com/org/repo"
    )


async def test_secrets_endpoint_returns_masked_descriptors(
    client: AsyncClient,
) -> None:
    from gitforce.app.security.secrets import SecretManager

    manager = SecretManager()
    manager.register()
    resp = await client.get("/api/security/secrets")
    assert resp.status_code == 200
    payload = resp.json()["secrets"]
    assert "GITHUB_TOKEN" in payload
    value = payload["GITHUB_TOKEN"]
    assert isinstance(value, str)
    assert "ghp_" not in value
    assert len(value) <= 9 or value in ("[set]", "[unset]")


async def test_create_task_is_idempotent(client: AsyncClient) -> None:
    from gitforce.app.security.recovery import idempotency_store

    idempotency_store._seen.clear()
    payload = {
        "repository_url": "https://github.com/org/repo",
        "issue_url": "https://github.com/org/repo/issues/42",
    }
    first = await client.post("/api/tasks", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/tasks", json=payload)
    assert second.status_code == 201
    assert first.json()["task_id"] == second.json()["task_id"]


async def test_create_task_different_issue_not_duplicate(
    client: AsyncClient,
) -> None:
    from gitforce.app.security.recovery import idempotency_store

    idempotency_store._seen.clear()
    base = {"repository_url": "https://github.com/org/repo"}
    a = await client.post(
        "/api/tasks", json={**base, "issue_url": "https://github.com/org/repo/issues/1"}
    )
    b = await client.post(
        "/api/tasks", json={**base, "issue_url": "https://github.com/org/repo/issues/2"}
    )
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["task_id"] != b.json()["task_id"]
