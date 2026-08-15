from __future__ import annotations

from gitforce.app.mcp.base import ToolResult
from gitforce.app.mcp.permissions import AgentPermissions
from gitforce.app.mcp.registry import MCPRegistry


class MCPClient:
    """Agent-facing facade over the MCP registry.

    Every call is routed through the registry's permission gate, so agents
    cannot invoke a tool they are not allowed to use (sections 17, 44).
    """

    def __init__(
        self,
        registry: MCPRegistry,
        permissions: AgentPermissions | None = None,
    ) -> None:
        self._registry = registry
        self._permissions = permissions

    def bind(self, permissions: AgentPermissions) -> MCPClient:
        """Return a client bound to a specific agent's permissions."""
        return MCPClient(self._registry, permissions)

    def list_tools(self) -> list[dict]:
        return self._registry.list_tools()

    async def call(self, tool: str, args: dict | None = None) -> ToolResult:
        return await self._registry.call(
            tool, args, permissions=self._permissions
        )

    async def read_file(self, path: str) -> dict:
        result = await self.call("read_file", {"path": path})
        return result.data
