from __future__ import annotations

import re

from gitforce.app.agents.base import AgentBase
from gitforce.app.agents.models import SecurityResults
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.prompts.loader import load_prompt

_PATTERNS: list[tuple[str, str, str]] = [
    (
        "hardcoded_secret",
        "high",
        r"(?i)(api[_-]?key|secret|password|token)"
        r"\s*=\s*['\"][^'\"]+['\"]",
    ),
    (
        "unsafe_eval",
        "high",
        r"\b(eval|exec|os\.system|subprocess\.(run|Popen)"
        r"\s*\([^)]*shell\s*=\s*True)",
    ),
    (
        "sql_injection",
        "high",
        r"(?i)(execute|executemany)\s*\(\s*['\"].*\{"
        r"|\bf-string.*\bSELECT\b",
    ),
    ("path_traversal", "medium", r"open\(.*\.\./"),
    ("pickle_load", "medium", r"\bpickle\.load\b"),
    (
        "insecure_config",
        "medium",
        r"(?i)(allow_unsafe|disable_ssl|verify\s*=\s*False"
        r"|DEBUG\s*=\s*True)",
    ),
    ("weak_http", "low", r"http://"),
]


class SecurityAgent:
    """Static security scan + LLM interpretation (section 21)."""

    def __init__(self, provider: BaseLLMProvider) -> None:
        self._agent = AgentBase(provider)

    def static_scan(self, files: dict[str, str]) -> str:
        lines: list[str] = []
        for path, content in files.items():
            for lineno, line in enumerate(content.splitlines(), start=1):
                for label, severity, pattern in _PATTERNS:
                    if re.search(pattern, line):
                        lines.append(
                            f"{path}:{lineno} [{severity}] {label}: {line.strip()}"
                        )
        return "\n".join(lines) or "No obvious static markers found."

    async def analyze(
        self,
        scan_context: str,
        changed_files: list[str],
    ) -> SecurityResults:
        prompt = (
            load_prompt("security", "analyze")
            .replace("{{security_scan}}", scan_context)
            .replace("{{changed_files}}", "\n".join(changed_files) or "(none)")
        )
        return await self._agent.run_structured(
            prompt, SecurityResults, max_tokens=1200
        )