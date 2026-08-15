from __future__ import annotations

import importlib.resources
from pathlib import Path

_NAMESPACE = "gitforce.prompts"


class PromptNotFoundError(FileNotFoundError):
    pass


def load_prompt(subdir: str, name: str) -> str:
    """Load a versioned prompt template from the prompts package.

    Versioned files use the pattern ``<name>.v<N>.txt``; an unversioned
    ``<name>.txt`` is used as a fallback so callers do not need to pin
    versions.
    """
    package_dir = _prompts_dir()
    sub = package_dir.joinpath(subdir)
    if not sub.is_dir():
        raise PromptNotFoundError(f"Prompt directory not found: {subdir}")

    candidates = [f"{name}.txt"]
    versioned = sorted(
        (p for p in sub.iterdir() if p.name.startswith(f"{name}.v")),
        key=lambda p: _version_of(p.name, name),
        reverse=True,
    )
    if versioned:
        candidates.insert(0, versioned[0].name)

    for candidate in candidates:
        target = sub.joinpath(candidate)
        if target.is_file():
            return target.read_text(encoding="utf-8")
    raise PromptNotFoundError(f"Prompt not found: {subdir}/{name}")


def _version_of(filename: str, prefix: str) -> tuple[int, ...]:
    stem = filename[len(prefix) + 1 : -len(".txt")]
    parts = stem.split(".") if stem else []
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (0,)


def _prompts_dir() -> Path:
    return Path(importlib.resources.files(_NAMESPACE))  # type: ignore[arg-type]


def repo_root() -> Path:
    """Filesystem path to the prompts directory (for tooling/CI checks)."""
    return Path(__file__).resolve().parent