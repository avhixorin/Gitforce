from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from gitforce.app.mcp.permissions import PermissionLevel


class ToolInput(BaseModel):
    """Per-tool input schema; subclasses add concrete fields."""


@dataclass
class Tool:
    """A tool exposed by an MCP server (section 17)."""

    name: str
    description: str
    permission: PermissionLevel
    handler: Any
    input_schema: type[ToolInput] | None = None

    def parse_args(self, args: dict) -> dict:
        if self.input_schema is None:
            return args
        return self.input_schema.model_validate(args).model_dump()


@dataclass
class ToolResult:
    tool: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
        }


class MCPServer(ABC):
    """Base class for ForgeAI MCP servers (section 17)."""

    name: str = "base"

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._register_tools()

    @abstractmethod
    def _register_tools(self) -> None: ...

    def _tool(
        self,
        name: str,
        description: str,
        permission: PermissionLevel,
        handler: Any,
        input_schema: type[ToolInput] | None = None,
    ) -> None:
        self._tools[name] = Tool(
            name=name,
            description=description,
            permission=permission,
            handler=handler,
            input_schema=input_schema,
        )

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "permission": tool.permission.value,
                "input_schema": (
                    tool.input_schema.model_json_schema()
                    if tool.input_schema
                    else None
                ),
            }
            for tool in self._tools.values()
        ]

    async def call(
        self, name: str, args: dict | None = None
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                tool=name, ok=False, error=f"Unknown tool '{name}'"
            )
        try:
            parsed = tool.parse_args(args or {})
            data = await tool.handler(**parsed)
            return ToolResult(tool=name, ok=True, data=data)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool=name, ok=False, error=f"{type(exc).__name__}: {exc}"
            )
