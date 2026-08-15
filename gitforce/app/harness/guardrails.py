from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class GuardrailViolation(Exception):
    """Raised when a safety guardrail rejects an action (section 44)."""


@dataclass
class SecretRedactor:
    """Redacts known secret shapes so they never reach prompts or logs
    (section 44: never expose secrets to LLM prompts, redact from logs)."""

    patterns: tuple[str, ...] = (
        r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[=:]\s*\S+",
        r"sk-[A-Za-z0-9_\-]{16,}",
        r"(?i)ghp_[A-Za-z0-9]{20,}",
        r"Bearer\s+[A-Za-z0-9_\-\.]{16,}",
    )
    replacement: str = "[REDACTED]"

    def redact(self, text: str) -> str:
        for pattern in self.patterns:
            text = re.sub(
                pattern,
                lambda m: m.group(0).split("=")[0].split(":")[0]
                + self.replacement,
                text,
            )
        return text


class PathGuardrail:
    """Prevents arbitrary host filesystem access outside a workspace root
    (section 44: prevent arbitrary host filesystem access)."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def allow(self, candidate: str | Path) -> Path:
        resolved = (self._root / candidate).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise GuardrailViolation(
                f"Path escapes workspace root: {candidate}"
            ) from None
        return resolved


@dataclass
class CommandAllowlist:
    """Enforces a command allowlist for sandbox execution
    (section 44: enforce command allowlists where appropriate)."""

    allowed_prefixes: tuple[str, ...] = (
        "python",
        "pytest",
        "ruff",
        "mypy",
        "build",
        "bandit",
        "pip",
        "git",
    )
    blocked_substrings: tuple[str, ...] = (
        "rm -rf",
        "sudo",
        "> /dev",
        "2>/dev",
        "&&",
        "||",
        "curl",
        "wget",
        "nc ",
        "shutdown",
        "reboot",
    )

    def allow(self, argv: list[str]) -> list[str]:
        if not argv:
            raise GuardrailViolation("Empty command")
        joined = " ".join(argv)
        if any(blocked in joined for blocked in self.blocked_substrings):
            raise GuardrailViolation(f"Command blocked by allowlist: {joined}")
        if not argv[0].startswith(self.allowed_prefixes):
            raise GuardrailViolation(f"Command not in allowlist: {argv[0]}")
        return argv
