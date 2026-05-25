import os
from pathlib import Path
from typing import Literal

import tiktoken
from langchain_core.runnables import RunnableConfig
from rich.console import Console

from cortexdocs.agents.state import PipelineState
from cortexdocs.config import Settings
from cortexdocs.ingest.models import IngestedRepo, SourceFile

console = Console()

_SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", "build", ".next", ".vite", "coverage"}
_SKIP_EXTENSIONS = {".lock", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot"}
_TEXT_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".txt", ".yaml", ".yml", ".env", ".toml", ".py"}

_encoder = tiktoken.get_encoding("cl100k_base")


def _classify(path: str, content: str) -> Literal["mcp_registration", "handler", "config", "test", "util", "docs", "other"]:
    if "server.setRequestHandler" in content or "server.tool(" in content or "registerTool(" in content:
        return "mcp_registration"
    if "setRequestHandler" in content or "router." in content or "app.get(" in content or "app.post(" in content:
        return "handler"
    if any(kw in path.lower() for kw in ("config", "settings", ".env")):
        return "config"
    if any(kw in path for kw in (".test.", ".spec.", "__tests__")):
        return "test"
    ext = Path(path).suffix.lower()
    if ext == ".md":
        return "docs"
    if ext in {".ts", ".tsx", ".js", ".jsx", ".py"}:
        return "util"
    return "other"


def walk_repo(repo_path: str, token_budget: int = 200_000) -> IngestedRepo:
    root = Path(repo_path).resolve()
    files: list[SourceFile] = []
    skipped: list[str] = []
    tokens_used = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for filename in filenames:
            abs_path = Path(dirpath) / filename
            ext = abs_path.suffix.lower()

            if ext in _SKIP_EXTENSIONS:
                continue
            if ext not in _TEXT_EXTENSIONS:
                continue

            rel_path = str(abs_path.relative_to(root))
            size = abs_path.stat().st_size

            try:
                raw = abs_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                skipped.append(rel_path)
                continue

            file_tokens = len(_encoder.encode(raw))

            if tokens_used + file_tokens > token_budget:
                skipped.append(rel_path)
                files.append(SourceFile(
                    path=rel_path,
                    classification=_classify(rel_path, ""),
                    size_bytes=size,
                    content=None,
                ))
                continue

            tokens_used += file_tokens
            classification = _classify(rel_path, raw)
            files.append(SourceFile(
                path=rel_path,
                classification=classification,
                size_bytes=size,
                content=raw,
            ))

    console.print(
        f"  [dim]Ingested {len(files)} files ({tokens_used:,} tokens), "
        f"skipped {len(skipped)} over budget[/dim]"
    )
    return IngestedRepo(
        root_path=str(root),
        files=files,
        total_files=len(files),
        skipped_files=skipped,
    )


def ingest_node(state: PipelineState, config: RunnableConfig) -> dict:
    settings: Settings = config["configurable"]["settings"]

    console.print("[bold]Ingest:[/bold] Walking repo...")
    repo = walk_repo(str(settings.repo_path), settings.file_token_budget)

    return {"ingested_repo": repo}
