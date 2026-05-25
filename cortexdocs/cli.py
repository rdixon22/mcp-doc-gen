import asyncio
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from cortexdocs.config import Settings

app = typer.Typer(help="CortexDocs — AI documentation generator for MCP servers")
console = Console()


def _load_settings(
    server_cmd: str | None,
    server_url: str | None,
    server_cmd_cwd: str | None,
    repo: str | None,
    no_eval: bool,
) -> Settings:
    overrides: dict = {}
    if server_cmd is not None:
        overrides["server_cmd"] = server_cmd
    if server_url is not None:
        overrides["server_url"] = server_url
    if server_cmd_cwd is not None:
        overrides["server_cmd_cwd"] = server_cmd_cwd
    if repo is not None:
        overrides["repo_path"] = repo
    if no_eval:
        overrides["run_eval"] = False
    return Settings(**overrides)


@app.command()
def generate(
    server_cmd: Annotated[Optional[str], typer.Option(help="Shell command to launch MCP server via stdio")] = None,
    server_url: Annotated[Optional[str], typer.Option(help="URL of a running MCP HTTP server")] = None,
    server_cmd_cwd: Annotated[Optional[str], typer.Option(help="Working directory for --server-cmd")] = None,
    repo: Annotated[Optional[str], typer.Option(help="Path to source repo for Phase 2 enrichment")] = None,
    no_eval: Annotated[bool, typer.Option("--no-eval", help="Skip evaluation harness")] = False,
    from_stage: Annotated[Optional[str], typer.Option(help="Resume from stage: write | render | eval")] = None,
) -> None:
    """Run the full documentation generation pipeline."""
    try:
        settings = _load_settings(server_cmd, server_url, server_cmd_cwd, repo, no_eval)
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    _print_config_summary(settings, from_stage)

    if from_stage is None or from_stage == "discover":
        manifest = asyncio.run(_run_discover(settings))
    else:
        console.print("[dim]Skipping discovery — loading manifest from disk[/dim]")
        from cortexdocs.discovery.models import MCPServerManifest
        manifest = MCPServerManifest.model_validate_json(
            (settings.output_dir / "manifest.json").read_text()
        )

    # For --from-stage write: also load cached research (skip ingest + researcher)
    research = None
    if from_stage in ("write", "render") and settings.repo_path:
        research_path = settings.output_dir / "research.json"
        if research_path.exists():
            from cortexdocs.agents.state import ResearchOutput
            research = ResearchOutput.model_validate_json(research_path.read_text())
            console.print(f"[dim]Loaded research from {research_path}[/dim]")
        else:
            console.print(
                f"[yellow]Warning:[/yellow] --from-stage {from_stage} requested but "
                f"{research_path} not found — will run without research context"
            )

    _run_pipeline(settings, manifest, from_stage, research)


@app.command()
def serve() -> None:
    """Serve the generated docs site locally."""
    import subprocess
    mkdocs_yml = Path("output/mkdocs.yml")
    if not mkdocs_yml.exists():
        console.print("[red]No output/mkdocs.yml found. Run 'generate' first.[/red]")
        raise typer.Exit(1)
    subprocess.run(["mkdocs", "serve", "--config-file", str(mkdocs_yml)], check=True)


@app.command()
def eval_docs() -> None:
    """Re-run the evaluation harness against existing generated output."""
    console.print("[yellow]Eval harness not yet implemented (Day 4).[/yellow]")


def _print_token_summary(token_usage: dict) -> None:
    if not token_usage:
        return
    table = Table(title="Token Usage", show_header=True, box=None, padding=(0, 2))
    table.add_column("type", style="dim")
    table.add_column("tokens", justify="right")
    table.add_row("input", str(token_usage.get("input", 0)))
    table.add_row("output", str(token_usage.get("output", 0)))
    table.add_row("cache read", str(token_usage.get("cache_read", 0)))
    table.add_row("cache write", str(token_usage.get("cache_write", 0)))
    console.print(table)


def _print_config_summary(settings: Settings, from_stage: str | None) -> None:
    table = Table(title="CortexDocs — Run Configuration", show_header=False, box=None, padding=(0, 1))
    table.add_column("key", style="dim")
    table.add_column("value")

    transport = f"stdio: {settings.server_cmd}" if settings.server_cmd else f"http: {settings.server_url}"
    table.add_row("transport", transport)
    if settings.server_cmd_cwd:
        table.add_row("cwd", settings.server_cmd_cwd)
    table.add_row("repo enrichment", str(settings.repo_path) if settings.repo_path else "disabled (Phase 1 only)")
    table.add_row("eval", "enabled" if settings.run_eval else "disabled")
    table.add_row("output dir", str(settings.output_dir))
    if from_stage:
        table.add_row("resuming from", from_stage)

    console.print(table)
    console.print()


async def _run_discover(settings: Settings):
    from cortexdocs.discovery.mcp_client import discover

    console.print("[bold]Phase 1:[/bold] Connecting to MCP server...")
    manifest = await discover(settings)

    output_path = settings.output_dir / "manifest.json"
    output_path.write_text(manifest.model_dump_json(indent=2))

    console.print(f"[green]✓[/green] Discovered [bold]{len(manifest.tools)}[/bold] tools from [bold]{manifest.server_name}[/bold] v{manifest.server_version or '?'}")
    for tool in manifest.tools:
        console.print(f"  [dim]·[/dim] {tool.name}")
    if manifest.resources:
        console.print(f"  [dim]+[/dim] {len(manifest.resources)} resource(s)")
    if manifest.prompts:
        console.print(f"  [dim]+[/dim] {len(manifest.prompts)} prompt(s)")
    console.print(f"\n[dim]Manifest saved to {output_path}[/dim]")
    return manifest


def _run_pipeline(settings: Settings, manifest, from_stage: str | None, research=None) -> None:
    import time

    from langgraph.checkpoint.sqlite import SqliteSaver

    from cortexdocs.agents.graph import build_graph, initial_state

    console.print()
    db_path = str(settings.output_dir / "checkpoints.db")

    # When resuming from write/render, skip the Phase 2 graph nodes even if REPO_PATH is set.
    # We inject any cached research directly into the initial state instead.
    graph_settings = settings
    if from_stage in ("write", "render") and settings.repo_path:
        graph_settings = settings.model_copy(update={"repo_path": None})

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        graph = build_graph(graph_settings, checkpointer)
        state = initial_state(manifest, settings)

        # Inject pre-loaded research when skipping the researcher node
        if research is not None:
            state["research"] = research
            state["repo_enriched"] = True

        run_config = {
            "configurable": {
                "thread_id": f"run-{int(time.time())}",
                "settings": settings,
            }
        }

        try:
            final_state = graph.invoke(state, config=run_config)
        except NotImplementedError as e:
            console.print(f"\n[yellow]Pipeline stopped at stub:[/yellow] {e}")
            return

    console.print("\n[green]Pipeline complete.[/green]")
    _print_token_summary(final_state.get("token_usage", {}))
