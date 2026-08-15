from __future__ import annotations

from gitforce.app.mcp.base import MCPServer, Tool, ToolResult
from gitforce.app.mcp.permissions import (
    AgentPermissions,
    MCPPermissionError,
    PermissionCategory,
)


def _category_for_server(name: str) -> PermissionCategory:
    if name == "github":
        return PermissionCategory.GITHUB
    if name == "repository":
        return PermissionCategory.REPOSITORY
    if name == "execution":
        return PermissionCategory.EXECUTION
    return PermissionCategory.DOCUMENTATION


class MCPRegistry:
    """Registers MCP servers and dispatches tool calls through the
    permission model (sections 17, 44). No tool call bypasses this gate.
    """

    def __init__(self, servers: list[MCPServer] | None = None) -> None:
        self._servers: dict[str, MCPServer] = {}
        self._tools: dict[str, Tool] = {}
        self._categories: dict[str, PermissionCategory] = {}
        self._tool_servers: dict[str, MCPServer] = {}
        if servers:
            for server in servers:
                self.register(server)

    def register(self, server: MCPServer) -> None:
        self._servers[server.name] = server
        category = _category_for_server(server.name)
        for tool in server._tools.values():  # noqa: SLF001
            self._tools[tool.name] = tool
            self._categories[tool.name] = category
            self._tool_servers[tool.name] = server

    def list_servers(self) -> list[str]:
        return list(self._servers)

    def list_tools(self) -> list[dict]:
        return [
            {"server": self._categories[t.name].value, **t.__dict__}
            for t in self._tools.values()
        ]

    async def call(
        self,
        tool_name: str,
        args: dict | None = None,
        *,
        permissions: AgentPermissions | None = None,
    ) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(
                tool=tool_name, ok=False, error=f"Unknown tool '{tool_name}'"
            )
        category = self._categories[tool_name]
        perms = permissions or default_agent(tool_name)
        # The permission model is the only entry point.
        if not perms.can_call(tool_name, category, tool.permission):
            return ToolResult(
                tool=tool_name,
                ok=False,
                error=str(MCPPermissionError(tool_name, perms.agent)),
            )
        # Delegate to the owning server so results are uniformly wrapped.
        return await self._tool_servers[tool_name].call(
            tool_name, args or {}
        )


def default_agent(tool_name: str) -> AgentPermissions:
    """Fallback permissions used when the caller passes none."""
    from gitforce.app.mcp.permissions import default_permissions

    return default_permissions("default")
