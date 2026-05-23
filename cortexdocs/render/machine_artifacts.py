import json
from pathlib import Path

from cortexdocs.agents.state import DocPage
from cortexdocs.discovery.models import MCPServerManifest


def write_api_json(manifest: MCPServerManifest, approved_pages: list[DocPage], output_dir: Path) -> None:
    """Serialise the manifest with doc_page links added. No LLM — authoritative from tools/list."""
    page_map = {p.spec.page_id: p.spec.filename for p in approved_pages}

    tools = []
    for tool in manifest.tools:
        page_id = f"tool-{tool.name.replace('_', '-')}"
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.raw_input_schema,
            "doc_page": page_map.get(page_id),
        })

    payload = {
        "schema_version": "1.0",
        "generated_at": manifest.discovered_at,
        "server_name": manifest.server_name,
        "server_version": manifest.server_version,
        "transport": manifest.transport,
        "mcp_tools": tools,
        "resources": manifest.resources,
        "prompts": manifest.prompts,
    }

    (output_dir / "api.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_llms_txt(manifest: MCPServerManifest, approved_pages: list[DocPage], output_dir: Path) -> None:
    """llms.txt — table of contents following the llmstxt.org convention."""
    lines = [
        f"# {manifest.server_name}",
        "",
        f"> MCP server v{manifest.server_version or 'unknown'} — {len(manifest.tools)} tools",
        "",
    ]

    # Overview page link
    overview = next((p for p in approved_pages if p.spec.page_id == "overview"), None)
    if overview:
        lines += [f"## Overview", "", f"- [Overview](llms/{overview.spec.filename})", ""]

    # Tools index
    lines += ["## MCP Tools", ""]
    for tool in manifest.tools:
        page_id = f"tool-{tool.name.replace('_', '-')}"
        page = next((p for p in approved_pages if p.spec.page_id == page_id), None)
        if page:
            lines.append(f"- [{tool.name}](llms/{page.spec.filename}): {tool.description[:100]}")
        else:
            lines.append(f"- {tool.name}: {tool.description[:100]}")

    lines += ["", "## Pages", ""]
    for page in approved_pages:
        if page.spec.page_id not in ("overview",) and not page.spec.page_id.startswith("tool-"):
            lines.append(f"- [{page.spec.title}](llms/{page.spec.filename})")

    (output_dir / "llms.txt").write_text("\n".join(lines), encoding="utf-8")


def write_llms_full_txt(approved_pages: list[DocPage], output_dir: Path) -> None:
    """llms-full.txt — all approved pages concatenated, frontmatter stripped."""
    sections = []
    for page in approved_pages:
        content = _strip_frontmatter(page.content)
        sections.append(content.strip())

    (output_dir / "llms-full.txt").write_text("\n\n---\n\n".join(sections), encoding="utf-8")


def _strip_frontmatter(content: str) -> str:
    """Remove the leading YAML frontmatter block from a page."""
    content = content.strip()
    if not content.startswith("---"):
        return content
    end = content.find("\n---", 3)
    if end == -1:
        return content
    return content[end + 4:].strip()
