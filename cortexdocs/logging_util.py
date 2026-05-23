import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator


@contextmanager
def agent_log(
    agent: str,
    model: str,
    log_dir: Path,
    input_summary: str,
) -> Generator[dict[str, Any], None, None]:
    """Context manager that writes a structured JSON log entry for each agent call.

    Usage::

        with agent_log("planner", "claude-sonnet-4-6", log_dir, "16 tools") as log:
            response = client.messages.create(...)
            log["input_tokens"] = response.usage.input_tokens
            log["output_tokens"] = response.usage.output_tokens
            log["full_output"] = response.content[0].text
    """
    entry: dict[str, Any] = {
        "agent": agent,
        "model": model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_summary": input_summary,
    }
    t0 = time.monotonic()
    try:
        yield entry
    finally:
        entry["duration_s"] = round(time.monotonic() - t0, 2)
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        log_path = log_dir / f"{timestamp}_{agent}.json"
        log_path.write_text(json.dumps(entry, indent=2, default=str))


def accumulate_usage(token_usage: dict[str, int], usage: Any) -> dict[str, int]:
    """Merge Anthropic usage object into the running token_usage dict."""
    updated = dict(token_usage)
    updated["input"] = updated.get("input", 0) + getattr(usage, "input_tokens", 0)
    updated["output"] = updated.get("output", 0) + getattr(usage, "output_tokens", 0)
    updated["cache_read"] = updated.get("cache_read", 0) + getattr(usage, "cache_read_input_tokens", 0)
    updated["cache_write"] = updated.get("cache_write", 0) + getattr(usage, "cache_creation_input_tokens", 0)
    return updated
