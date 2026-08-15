from __future__ import annotations

import time
from datetime import datetime

import httpx
import jwt

from gitforce.app.config.settings import get_settings

_INSTALLATION_TOKEN_TTL = 3600


class GitHubAppAuthError(Exception):
    pass


def resolve_github_token_sync() -> str | None:
    """Best-effort sync token resolution for non-async call sites (e.g.
    git pushes). Only the classic token is available synchronously; the
    async ``GitHubAppAuthenticator.get_token`` handles app installation
    tokens."""
    return get_settings().github_token


class GitHubAppAuthenticator:
    """GitHub App authentication (section 45): a signed app JWT is exchanged
    for a short-lived installation access token, avoiding long-lived PATs.

    The private key is read from ``github_app_private_key_path``; if the
    app is not configured, the classic ``github_token`` is used as a
    fallback so the platform still works with a personal token.
    """

    def __init__(self, settings=None) -> None:
        self._settings = settings or get_settings()
        self._installation_token: str | None = None
        self._installation_token_expires_at: float = 0.0
        self._http = httpx.AsyncClient(
            base_url="https://api.github.com", timeout=30
        )

    @property
    def configured(self) -> bool:
        return bool(
            self._settings.github_app_id
            and self._settings.github_app_private_key_path
        )

    def _app_jwt(self) -> str:
        if not self._settings.github_app_id:
            raise GitHubAppAuthError("github_app_id is not configured")
        private_key_path = self._settings.github_app_private_key_path
        if not private_key_path:
            raise GitHubAppAuthError(
                "github_app_private_key_path is not configured"
            )
        try:
            with open(private_key_path, encoding="utf-8") as fh:
                private_key = fh.read()
        except OSError as exc:
            raise GitHubAppAuthError(
                f"Unable to read GitHub app private key: {exc}"
            ) from exc

        now = int(time.time())
        return jwt.encode(
            {
                "iat": now,
                "exp": now + 600,
                "iss": str(self._settings.github_app_id),
            },
            private_key,
            algorithm="RS256",
        )

    async def _fresh_installation_token(self) -> str:
        if not self.configured:
            raise GitHubAppAuthError("GitHub App is not configured")
        installation_id = self._settings.github_app_installation_id
        if not installation_id:
            raise GitHubAppAuthError(
                "github_app_installation_id is not configured"
            )
        jwt_token = self._app_jwt()
        resp = await self._http.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if resp.status_code != 201:
            raise GitHubAppAuthError(
                f"GitHub App token exchange failed: {resp.status_code} "
                f"{resp.text[:200]}"
            )
        data = resp.json()
        self._installation_token = data.get("token")
        expires_at = data.get("expires_at")
        self._installation_token_expires_at = (
            datetime.fromisoformat(
                expires_at.replace("Z", "+00:00")
            ).timestamp()
            if expires_at
            else time.time() + _INSTALLATION_TOKEN_TTL
        )
        if not self._installation_token:
            raise GitHubAppAuthError("GitHub App returned no access token")
        return self._installation_token

    async def get_token(self) -> str | None:
        """Return the best available GitHub token: a cached installation
        token when the app is configured, else the classic token."""
        if self.configured:
            now = time.time()
            if (
                self._installation_token
                and now < self._installation_token_expires_at - 60
            ):
                return self._installation_token
            return await self._fresh_installation_token()
        return self._settings.github_token

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> GitHubAppAuthenticator:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
