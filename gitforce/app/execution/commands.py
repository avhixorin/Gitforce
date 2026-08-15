from __future__ import annotations

import shlex

ALLOWED_COMMANDS: dict[str, set[str]] = {
    "test": {
        "pytest",
        "python",
        "python3",
        "pip",
        "pip3",
        "node",
        "npm",
        "yarn",
        "go",
        "cargo",
        "mvn",
        "gradle",
        "make",
        "tox",
        "flake8",
        "ruff",
        "mypy",
    },
    "build": {"python", "python3", "pip", "pip3", "node", "npm", "yarn", "go", "cargo", "make"},
    "inspect": {
        "ls",
        "cat",
        "find",
        "grep",
        "rg",
        "wc",
        "head",
        "tail",
        "git",
        "tree",
        "pwd",
        "echo",
        "python",
        "python3",
    },
}


class CommandDeniedError(PermissionError):
    def __init__(self, command: str, purpose: str) -> None:
        super().__init__(
            f"Command denied for purpose '{purpose}': {command!r}"
        )
        self.command = command
        self.purpose = purpose


def validate_command(
    argv: list[str], purpose: str = "test", workspace: str | None = None
) -> None:
    """Reject commands not on the allowlist and dangerous flags.

    Raises CommandDeniedError when the command is not permitted.
    """
    if not argv:
        raise CommandDeniedError("", purpose)
    base = argv[0].split("/")[-1]
    allowed = ALLOWED_COMMANDS.get(purpose, set())
    if base not in allowed:
        raise CommandDeniedError(argv[0], purpose)

    # Never allow redirection, pipes, or command substitution at the shell level.
    for arg in argv[1:]:
        if arg in {"&&", "||", ">", ">>", "<", "|", ";", "`"}:
            raise CommandDeniedError(base, purpose)


def parse_command(
    command: str | list[str], purpose: str = "test"
) -> list[str]:
    argv = shlex.split(command) if isinstance(command, str) else list(command)
    validate_command(argv, purpose=purpose)
    return argv