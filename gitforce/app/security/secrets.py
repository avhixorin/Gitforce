from __future__ import annotations

import re
from dataclasses import dataclass, field

from gitforce.app.config.settings import get_settings
from gitforce.app.harness.guardrails import SecretRedactor


@dataclass
class SecretManager:
    """Centralized secret management (Phase 12 / section 44).

    Loads the set of active secrets once from settings, registers them
    with the redactor so no secret value can leak into prompts or logs,
    and exposes a ``describe()`` view that reveals only masked values.
    """

    redactor: SecretRedactor = field(default_factory=SecretRedactor)

    @staticmethod
    def _secret_fields() -> dict[str, str | None]:
        settings = get_settings()
        return {
            "GITHUB_TOKEN": settings.github_token,
            "GITHUB_APP_PRIVATE_KEY_PATH": settings.github_app_private_key_path,
            "OPENAI_API_KEY": settings.openai_api_key,
            "ANTHROPIC_API_KEY": settings.anthropic_api_key,
            "GOOGLE_API_KEY": settings.google_api_key,
            "GROQ_API_KEY": settings.groq_api_key,
            "LOCAL_LLM_API_KEY": settings.local_llm_api_key,
            "LANGSMITH_API_KEY": settings.langsmith_api_key,
        }

    def register(self) -> SecretRedactor:
        """Add every configured secret value to the redactor so it is
        scrubbed from prompts, logs, and traces (section 44)."""
        for value in self._secret_fields().values():
            if value and len(value) >= 4:
                self.redactor.patterns = self.redactor.patterns + (
                    re.escape(value),
                )
        return self.redactor

    def describe(self) -> dict[str, str]:
        """Masked description of configured secrets for diagnostics."""
        out: dict[str, str] = {}
        for name, value in self._secret_fields().items():
            if value:
                out[name] = f"{value[:4]}…{value[-2:]}" if len(value) > 8 else "[set]"
            else:
                out[name] = "[unset]"
        return out
