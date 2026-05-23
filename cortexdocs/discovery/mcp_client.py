import os
import shlex
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import Tool

from cortexdocs.config import Settings
from cortexdocs.discovery.models import MCPServerManifest, MCPToolDef, MCPToolParam


async def discover(settings: Settings) -> MCPServerManifest:
    if settings.server_cmd:
        return await _discover_stdio(settings)
    return await _discover_http(settings)


def _build_server_env(settings: Settings) -> dict[str, str] | None:
    """Load extra env vars for the server process from an env file if specified."""
    if not settings.server_env_file:
        return None
    env_path = Path(settings.server_env_file)
    if not env_path.exists():
        return None
    extra = {k: v for k, v in dotenv_values(env_path).items() if v is not None}
    return {**os.environ, **extra}


async def _discover_stdio(settings: Settings) -> MCPServerManifest:
    parts = shlex.split(settings.server_cmd)
    server_params = StdioServerParameters(
        command=parts[0],
        args=parts[1:],
        cwd=settings.server_cmd_cwd,
        env=_build_server_env(settings),
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            return await _collect_manifest(session, init_result, "stdio")


async def _discover_http(settings: Settings) -> MCPServerManifest:
    headers: dict[str, str] = {}
    if settings.mcp_access_key:
        headers["x-cortex-key"] = settings.mcp_access_key

    async with streamablehttp_client(settings.server_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            return await _collect_manifest(session, init_result, "http")


async def _collect_manifest(session: ClientSession, init_result, transport) -> MCPServerManifest:
    server_info = init_result.serverInfo
    server_name = server_info.name if server_info else "unknown"
    server_version = server_info.version if server_info else None

    tools_result = await session.list_tools()
    tools = [_parse_tool(t) for t in tools_result.tools]

    resources: list[dict] = []
    try:
        resources_result = await session.list_resources()
        resources = [r.model_dump() for r in resources_result.resources]
    except Exception:
        pass

    prompts: list[dict] = []
    try:
        prompts_result = await session.list_prompts()
        prompts = [p.model_dump() for p in prompts_result.prompts]
    except Exception:
        pass

    return MCPServerManifest(
        server_name=server_name,
        server_version=server_version,
        tools=tools,
        resources=resources,
        prompts=prompts,
        transport=transport,
        discovered_at=datetime.now(timezone.utc).isoformat(),
    )


def _parse_tool(tool: Tool) -> MCPToolDef:
    schema = tool.inputSchema or {}
    # inputSchema is an AnnotatedInputSchema or plain dict — normalise to dict
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump(exclude_none=True)
    elif not isinstance(schema, dict):
        schema = {}

    properties: dict = schema.get("properties", {})
    required_fields: list[str] = schema.get("required", [])

    params = [
        MCPToolParam(
            name=name,
            description=prop.get("description") if isinstance(prop, dict) else None,
            json_type=prop.get("type", "unknown") if isinstance(prop, dict) else "unknown",
            required=name in required_fields,
            param_schema=prop if isinstance(prop, dict) else {},
        )
        for name, prop in properties.items()
    ]

    return MCPToolDef(
        name=tool.name,
        description=tool.description or "",
        params=params,
        raw_input_schema=schema,
    )
