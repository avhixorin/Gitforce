from __future__ import annotations

import enum
from dataclasses import dataclass, field


class MCPPermissionError(PermissionError):
    """Raised when a tool call is blocked by the permission model (17)."""

    def __init__(self, tool: str, agent: str) -> None:
        super().__init__(
            f"Agent '{agent}' is not permitted to call tool '{tool}'"
        )
        self.tool = tool
        self.agent = agent


class PermissionLevel(enum.StrEnum):
    """Scoped permission levels for MCP tools (sections 17, 44).

    Order matters: READ < EXECUTE < WRITE. A tool requires its declared
    permission level; an agent granted a higher level may call it.
    """

    READ = "read"
    EXECUTE = "execute"
    WRITE = "write"

    @property
    def rank(self) -> int:
        return {
            PermissionLevel.READ: 0,
            PermissionLevel.EXECUTE: 1,
            PermissionLevel.WRITE: 2,
        }[self]


def level_allows(granted: PermissionLevel, required: PermissionLevel) -> bool:
    """True when a grant covers a requirement (higher is more permissive)."""
    return granted.rank >= required.rank


class PermissionCategory(enum.StrEnum):
    """Tool categories so permissions can be restricted per area."""

    GITHUB = "github"
    REPOSITORY = "repository"
    EXECUTION = "execution"
    DOCUMENTATION = "documentation"


# Dangerous / high-impact tools are never allowed by default; they require an
# explicit grant and (in later phases) human approval.
_DEFAULT_RESTRICTED: dict[str, PermissionLevel] = {
    "github": PermissionLevel.WRITE,
    "execution": PermissionLevel.EXECUTE,
    "repository": PermissionLevel.READ,
    "documentation": PermissionLevel.READ,
}

_ALWAYS_BLOCKED = {
    "create_fork",
    "create_branch",
    "push_changes",
    "create_pull_request",
    "update_pull_request",
    "reply_to_comment",
}


@dataclass
class AgentPermissions:
    """Permissions granted to a single agent (section 44: restrict by agent).

    ``allowed`` maps category -> granted level. ``blocked`` is an explicit
    denylist of tool names that override any grant (defence in depth).
    """

    agent: str
    allowed: dict[PermissionCategory, PermissionLevel] = field(
        default_factory=lambda: {
            PermissionCategory.GITHUB: PermissionLevel.READ,
            PermissionCategory.REPOSITORY: PermissionLevel.READ,
            PermissionCategory.EXECUTION: PermissionLevel.READ,
            PermissionCategory.DOCUMENTATION: PermissionLevel.READ,
        }
    )
    blocked: set[str] = field(default_factory=set)

    def can_call(
        self, tool_name: str, category: PermissionCategory, required: PermissionLevel
    ) -> bool:
        if tool_name in _ALWAYS_BLOCKED or tool_name in self.blocked:
            return False
        granted = self.allowed.get(category, PermissionLevel.READ)
        return level_allows(granted, required)


def default_permissions(agent: str) -> AgentPermissions:
    """Sensible defaults: read-only everywhere, execute where granted."""
    allowed = {
        PermissionCategory.GITHUB: PermissionLevel.READ,
        PermissionCategory.REPOSITORY: PermissionLevel.READ,
        PermissionCategory.EXECUTION: PermissionLevel.READ,
        PermissionCategory.DOCUMENTATION: PermissionLevel.READ,
    }
    return AgentPermissions(agent=agent, allowed=allowed)


def agent_with_extra(
    agent: str, *, execution: PermissionLevel | None = None,
    repository: PermissionLevel | None = None,
) -> AgentPermissions:
    """Create permissions with specific areas elevated."""
    perms = default_permissions(agent)
    if execution is not None:
        perms.allowed[PermissionCategory.EXECUTION] = execution
    if repository is not None:
        perms.allowed[PermissionCategory.REPOSITORY] = repository
    return perms


def check_tool(
    perms: AgentPermissions,
    tool_name: str,
    category: PermissionCategory,
    required: PermissionLevel,
) -> None:
    """Enforce the permission model; raise if the agent cannot call the tool."""
    if not perms.can_call(tool_name, category, required):
        raise MCPPermissionError(tool_name, perms.agent)
