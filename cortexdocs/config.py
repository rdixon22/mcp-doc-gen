from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""

    # Phase 1 — at least one of these must be set
    server_cmd: str | None = None        # e.g. "npx tsx src/server/mcp-stdio.ts"
    server_url: str | None = None        # e.g. "http://localhost:3000/mcp"
    server_cmd_cwd: str | None = None    # working dir when spawning stdio process
    server_env_file: str | None = None   # path to .env file to load for the server process
    mcp_access_key: str | None = None    # sent as x-cortex-key header (HTTP only)

    # Phase 2 — optional repo enrichment
    repo_path: str | None = None

    # Models
    researcher_model: str = "claude-opus-4-7"
    writer_model: str = "claude-sonnet-4-6"
    reviewer_model: str = "claude-opus-4-7"
    judge_model: str = "claude-opus-4-7"

    # Pipeline limits
    max_revision_rounds: int = 2
    file_token_budget: int = 200_000
    file_inline_threshold_tokens: int = 2_000

    # Output
    run_eval: bool = True
    log_dir: Path = Path("logs")
    output_dir: Path = Path("output")

    @model_validator(mode="after")
    def require_server_connection(self) -> "Settings":
        if not self.server_cmd and not self.server_url:
            raise ValueError("At least one of SERVER_CMD or SERVER_URL must be set")
        return self
