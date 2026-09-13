"""Public Strands adapters over the strict shared HTTP command registry."""

from __future__ import annotations

from typing import Any

from strands.types._events import ToolResultEvent
from strands.types.tools import AgentTool, ToolGenerator, ToolSpec, ToolUse

from .client import StewardHttpClient
from .protocol import OPERATIONS, Command, build_command, error, input_json


class StewardAgentTool(AgentTool):
    def __init__(self, operation: str, client: StewardHttpClient) -> None:
        super().__init__()
        self.operation = OPERATIONS[operation]
        self.client = client

    @property
    def tool_name(self) -> str:
        return self.operation.name

    @property
    def tool_type(self) -> str:
        return "function"

    @property
    def tool_spec(self) -> ToolSpec:
        schema = self.operation.model.model_json_schema()

        def bounds(node):
            if isinstance(node, dict):
                if node.get("type") == "string":
                    node["maxLength"] = min(node.get("maxLength", 2000), 2000)
                if node.get("type") == "array":
                    node["maxItems"] = min(node.get("maxItems", 64), 64)
                for name, prop in node.get("properties", {}).items():
                    if name.endswith("_id") and prop.get("type") == "string":
                        prop["pattern"] = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$"
                for value in node.values():
                    bounds(value)
            elif isinstance(node, list):
                for value in node:
                    bounds(value)

        bounds(schema)
        return {
            "name": self.tool_name,
            "description": self.operation.description,
            "inputSchema": {"json": schema},
        }

    async def stream(
        self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any
    ) -> ToolGenerator:
        ref = tool_use.get("toolUseId")
        envelope = error("INVALID_TOOL_INPUT")
        try:
            if (
                type(ref) is not str
                or not 1 <= len(ref) <= 200
                or tool_use.get("name") != self.tool_name
            ):
                raise ValueError("invalid tool identity")
            value = self.operation.model.model_validate_json(input_json(tool_use.get("input")))
            command = self._command(value.model_dump(mode="json", exclude_unset=True))
        except (ValueError, TypeError, RecursionError, OverflowError):
            pass
        else:
            envelope = await self.client.execute(command, call_ref=ref)
        yield ToolResultEvent(
            {
                "toolUseId": ref if type(ref) is str else "invalid-tool-use",
                "status": "error" if envelope["outcome"] == "ERROR" else "success",
                "content": [{"json": envelope}],
            }
        )

    def _command(self, values: dict[str, Any]) -> Command:
        return build_command(self.tool_name, values)
