from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from gitforce.app.main import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_index_serves_spa(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Gitforce" in resp.text


async def test_static_css_served(client: AsyncClient) -> None:
    resp = await client.get("/static/styles.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]
    assert ".topbar" in resp.text


async def test_static_js_served(client: AsyncClient) -> None:
    resp = await client.get("/static/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert "renderCreate" in resp.text


async def test_favicon_served(client: AsyncClient) -> None:
    resp = await client.get("/favicon.ico")
    assert resp.status_code == 200
    assert "image/svg" in resp.headers["content-type"]


async def test_task_creation_form_fields_present(client: AsyncClient) -> None:
    # Section 5.1: repo URL + issue URL inputs and a Start button. The form
    # is rendered client-side, so inspect the served JS.
    js = (await client.get("/static/app.js")).text
    assert 'name="repository_url"' in js
    assert 'name="issue_url"' in js
    assert "Start Task" in js
    # Optional configuration fields per 5.1.
    assert 'name="target_branch"' in js
    assert 'name="model"' in js
    assert 'name="max_iterations"' in js
    assert 'name="test_execution_mode"' in js
    assert 'name="approval_mode"' in js
