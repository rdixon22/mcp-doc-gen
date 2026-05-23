from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel


class MCPToolParam(BaseModel):
    name: str
    description: str | None = None
    json_type: str                # JSON Schema "type" value
    required: bool
    param_schema: dict            # full property schema from inputSchema


class MCPToolDef(BaseModel):
    name: str
    description: str
    params: list[MCPToolParam]
    raw_input_schema: dict        # verbatim inputSchema from tools/list


class MCPServerManifest(BaseModel):
    server_name: str
    server_version: str | None
    tools: list[MCPToolDef]
    resources: list[dict]
    prompts: list[dict]
    transport: Literal["stdio", "http"]
    discovered_at: str            # ISO timestamp

    @classmethod
    def empty(cls, name: str, transport: Literal["stdio", "http"]) -> "MCPServerManifest":
        return cls(
            server_name=name,
            server_version=None,
            tools=[],
            resources=[],
            prompts=[],
            transport=transport,
            discovered_at=datetime.now(timezone.utc).isoformat(),
        )
