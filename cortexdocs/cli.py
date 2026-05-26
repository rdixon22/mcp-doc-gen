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

    # --from-stage render: skip all LLM calls, re-render existing pages from disk
    if from_stage == "render":
        _run_render_only(settings, manifest)
        return

    # For --from-stage write: load cached research (skip ingest + researcher)
    research = None
    if from_stage == "write" and settings.repo_path:
        research_path = settings.output_dir / "research.json"
        if research_path.exists():
            from cortexdocs.agents.state import ResearchOutput
            research = ResearchOutput.model_validate_json(research_path.read_text())
            console.print(f"[dim]Loaded research from {research_path}[/dim]")
        else:
            console.print(
                f"[yellow]Warning:[/yellow] --from-stage write requested but "
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
    """Run the evaluation harness against existing generated output."""
    try:
        settings = Settings()
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)

    from cortexdocs.eval.harness import run_eval
    from cortexdocs.eval.report import generate_report

    console.print("[bold]Running eval harness[/bold] (15 questions × 3 contexts × judge)...\n")
    results = run_eval(settings)
    report_path = generate_report(results, settings.output_dir)
    console.print(f"\n[green]✓[/green] Eval complete — report written to [bold]{report_path}[/bold]")


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


def _infer_page_id(rel_path: str) -> str:
    """Derive a stable page_id from a relative page filename."""
    stem = rel_path.replace("\\", "/").removesuffix(".md")
    if stem == "index":
        return "overview"
    if stem == "tools/index":
        return "tools-index"
    if stem.startswith("tools/"):
        return "tool-" + stem[len("tools/"):]
    return stem  # e.g. "architecture", "setup", "extending"


def _infer_title(page_id: str) -> str:
    known = {
        "overview": "Overview",
        "tools-index": "Tools",
        "architecture": "Architecture",
        "setup": "Setup Guide",
        "extending": "Extension Guide",
    }
    if page_id in known:
        return known[page_id]
    if page_id.startswith("tool-"):
        return page_id[len("tool-"):].replace("-", "_")
    return page_id.replace("-", " ").title()


def _run_render_only(settings: Settings, manifest) -> None:
    """Re-render existing pages from output/pages/ without any LLM calls."""
    import subprocess
    import sys

    from cortexdocs.agents.state import DocPage, DocPageSpec, DocPlan
    from cortexdocs.render.human_site import _build_nav, _prepare_docs_dir, _write_mkdocs_yml
    from cortexdocs.render.machine_artifacts import write_api_json, write_llms_full_txt, write_llms_txt

    pages_dir = settings.output_dir / "pages"
    if not pages_dir.exists():
        console.print(f"[red]No pages directory at {pages_dir}. Run generate first.[/red]")
        raise typer.Exit(1)

    approved_pages: list[DocPage] = []
    for md_file in sorted(pages_dir.rglob("*.md")):
        rel = md_file.relative_to(pages_dir).as_posix()
        content = md_file.read_text(encoding="utf-8")
        page_id = _infer_page_id(rel)
        title = _infer_title(page_id)
        phase = 2 if page_id in ("architecture", "setup", "extending") else 1
        spec = DocPageSpec(
            page_id=page_id,
            title=title,
            filename=rel,
            audience="both",
            phase=phase,
            key_points=[],
        )
        approved_pages.append(DocPage(spec=spec, content=content, review_status="approved"))

    console.print(f"\n[bold]Render:[/bold] {len(approved_pages)} pages from disk")

    doc_plan = DocPlan(pages=[p.spec for p in approved_pages])

    write_api_json(manifest, approved_pages, settings.output_dir)
    write_llms_txt(manifest, approved_pages, settings.output_dir)
    write_llms_full_txt(approved_pages, settings.output_dir)
    console.print("  [green]✓[/green] api.json, llms.txt, llms-full.txt")

    site_src = settings.output_dir / "site_src"
    docs_dir = site_src / "docs"
    _prepare_docs_dir(docs_dir, approved_pages, manifest.server_name)

    mkdocs_yml_path = settings.output_dir / "mkdocs.yml"
    nav = _build_nav(doc_plan, approved_pages)
    _write_mkdocs_yml(mkdocs_yml_path, manifest.server_name, docs_dir, settings.output_dir / "site", nav)
    console.print("  [green]✓[/green] mkdocs.yml")

    mkdocs_bin = Path(sys.executable).parent / "mkdocs"
    result = subprocess.run(
        [str(mkdocs_bin), "build", "--config-file", str(mkdocs_yml_path), "--quiet"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(f"  [red]mkdocs build failed:[/red]\n{result.stderr}")
    else:
        console.print(f"  [green]✓[/green] Site built → {settings.output_dir}/site/")

    console.print("\n[green]Render complete.[/green]")


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
