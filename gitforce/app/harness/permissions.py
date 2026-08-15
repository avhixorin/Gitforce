from __future__ import annotations

import enum
from dataclasses import dataclass, field


class PermissionDenied(PermissionError):
    """Raised when an agent attempts an action it was not granted."""

    def __init__(self, permission: str, agent: str) -> None:
        super().__init__(
            f"Agent '{agent}' is not granted permission '{permission}'"
        )
        self.permission = permission
        self.agent = agent


class Permission(enum.StrEnum):
    """String permissions per section 16. Anything not listed is denied."""

    REPO_READ = "repo.read"
    REPO_ISSUE_READ = "repo.issue.read"
    REPO_PR_READ = "repo.pr.read"
    REPO_MERGE = "repo.merge"  # dangerous: denied by default (44)

    WORKSPACE_READ = "workspace.read"
    WORKSPACE_WRITE = "workspace.write"
    WORKSPACE_EXECUTE = "workspace.execute"

    GIT_BRANCH_CREATE = "git.branch.create"
    GIT_COMMIT = "git.commit"
    GIT_PUSH = "git.push"

    PR_CREATE = "pr.create"
    PR_UPDATE = "pr.update"
    PR_COMMENT = "pr.comment"

    TESTS_EXECUTE = "tests.execute"
    SECRET_READ = "secret.read"  # noqa: S105  # dangerous: denied by default (44)
    PRODUCTION_EXECUTE = "production.execute"  # dangerous: denied (44)
    DATABASE_WRITE = "database.write"  # dangerous: denied by default (44)


# Dangerous permissions are never granted by default, even if requested.
DANGEROUS = {
    Permission.REPO_MERGE,
    Permission.SECRET_READ,
    Permission.PRODUCTION_EXECUTE,
    Permission.DATABASE_WRITE,
}


@dataclass
class AgentPermissions:
    """A set of string permissions granted to a single agent (section 16).

    Deny-by-default: an agent only has what is explicitly granted, and
    dangerous permissions are always stripped.
    """

    agent: str
    granted: set[Permission] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.granted = {p for p in self.granted if p not in DANGEROUS}

    def grants(self, permission: Permission) -> bool:
        return permission in self.granted

    def require(self, permission: Permission) -> None:
        """Enforce the permission; raise PermissionDenied when absent."""
        if not self.grants(permission):
            raise PermissionDenied(permission.value, self.agent)

    def add(self, permission: Permission) -> None:
        if permission not in DANGEROUS:
            self.granted.add(permission)

    def to_json(self) -> list[str]:
        return sorted(p.value for p in self.granted)


# Default grants per agent role. Mirror the MCP categories so the harness is
# the single source of truth for what each agent may touch.
DEFAULT_AGENT_PERMISSIONS: dict[str, set[Permission]] = {
    "coder": {
        Permission.REPO_READ,
        Permission.WORKSPACE_READ,
        Permission.WORKSPACE_WRITE,
    },
    "tester": {
        Permission.WORKSPACE_READ,
        Permission.TESTS_EXECUTE,
    },
    "security": {
        Permission.REPO_READ,
        Permission.WORKSPACE_READ,
    },
    "reviewer": {
        Permission.REPO_READ,
        Permission.WORKSPACE_READ,
    },
    "judge": {
        Permission.REPO_READ,
        Permission.REPO_PR_READ,
    },
    "planner": {
        Permission.REPO_READ,
        Permission.WORKSPACE_READ,
    },
    "requirements": {
        Permission.REPO_ISSUE_READ,
        Permission.REPO_PR_READ,
    },
    "repository": {
        Permission.REPO_READ,
        Permission.WORKSPACE_READ,
    },
    "failure_analyzer": {
        Permission.REPO_READ,
        Permission.WORKSPACE_READ,
    },
    "delivery": {
        Permission.REPO_READ,
        Permission.REPO_PR_READ,
        Permission.GIT_BRANCH_CREATE,
        Permission.GIT_COMMIT,
        Permission.GIT_PUSH,
        Permission.PR_CREATE,
        Permission.PR_UPDATE,
        Permission.PR_COMMENT,
    },
    "default": {Permission.REPO_READ, Permission.WORKSPACE_READ},
}


def permissions_for(agent: str) -> AgentPermissions:
    return AgentPermissions(
        agent=agent,
        granted=set(DEFAULT_AGENT_PERMISSIONS.get(agent, DEFAULT_AGENT_PERMISSIONS["default"])),
    )


def mcp_permissions_from(agent_permissions: AgentPermissions):
    """Derive MCP permission levels from harness grants so the MCP layer
    cannot exceed what the harness allowed (sections 17, 44)."""
    from gitforce.app.mcp.permissions import (
        AgentPermissions as MCPAgentPermissions,
    )
    from gitforce.app.mcp.permissions import PermissionCategory, PermissionLevel

    granted = agent_permissions.granted
    allowed: dict[PermissionCategory, PermissionLevel] = {}
    if Permission.REPO_READ in granted or Permission.REPO_PR_READ in granted:
        allowed[PermissionCategory.GITHUB] = PermissionLevel.READ
    if Permission.REPO_MERGE in granted or Permission.GIT_PUSH in granted:
        allowed[PermissionCategory.GITHUB] = PermissionLevel.WRITE
    if Permission.WORKSPACE_WRITE in granted:
        allowed[PermissionCategory.REPOSITORY] = PermissionLevel.WRITE
    elif Permission.WORKSPACE_READ in granted:
        allowed[PermissionCategory.REPOSITORY] = PermissionLevel.READ
    if Permission.TESTS_EXECUTE in granted:
        allowed[PermissionCategory.EXECUTION] = PermissionLevel.EXECUTE
    allowed[PermissionCategory.DOCUMENTATION] = PermissionLevel.READ
    return MCPAgentPermissions(
        agent=agent_permissions.agent, allowed=allowed, blocked=set()
    )
