"""Guardrail checks reported by check_config. Each returns (level, message)."""
import os
import subprocess
from pathlib import Path

from config.env import AppConfig
from extraction.pricing import is_known_model

OK, WARN, FAIL = "ok", "warn", "fail"


def _git(base_dir: Path, *args: str):
    try:
        return subprocess.run(
            ["git", *args], cwd=base_dir, capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None


def is_ignored(base_dir: Path, relative_path: str) -> bool | None:
    """True or False from git check-ignore, or None when git is not usable."""
    result = _git(base_dir, "check-ignore", "-q", relative_path)
    if result is None or result.returncode not in (0, 1):
        return None
    return result.returncode == 0


def run_checks(config: AppConfig, base_dir: Path, require_llm: bool = False) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    if config.anthropic_api_key is not None:
        results.append((OK, "ANTHROPIC_API_KEY is set."))
    else:
        level = FAIL if require_llm else WARN
        results.append((level, "ANTHROPIC_API_KEY is missing or a placeholder. Extraction cannot call the API until it is set in .env."))

    if is_known_model(config.claude_model):
        results.append((OK, f"Model {config.claude_model} has known pricing."))
    else:
        results.append((WARN, f"No pricing on file for {config.claude_model}. Cost estimates will use the highest known rate."))

    if config.allow_real_invoices_to_llm:
        results.append((WARN, "ALLOW_REAL_INVOICES_TO_LLM is true. Files outside data/synthetic can be sent to the Claude API."))
    else:
        results.append((OK, "Real invoices are blocked from the API. Only data/synthetic files can be sent."))

    if config.tms_mode == "mock":
        results.append((OK, "TMS_MODE is mock."))
    else:
        results.append((FAIL, f"TMS_MODE={config.tms_mode} is not supported yet. Only mock exists in this iteration."))

    if config.max_docs_per_run < 1 or config.run_cost_cap_usd <= 0:
        results.append((FAIL, "The per-run document cap and cost cap must be positive."))
    else:
        results.append((OK, f"Run caps are {config.max_docs_per_run} documents and ${config.run_cost_cap_usd}."))

    env_file = base_dir / ".env"
    if env_file.exists():
        tracked = _git(base_dir, "ls-files", "--error-unmatch", ".env")
        if tracked is not None and tracked.returncode == 0:
            results.append((FAIL, ".env is tracked by git. Remove it from the index before continuing."))
        else:
            results.append((OK, ".env is not tracked by git."))
        if os.name == "posix" and env_file.stat().st_mode & 0o077:
            results.append((WARN, ".env permissions are too open. Run chmod 600 .env."))
    else:
        results.append((WARN, "No .env file found. Copy .env.example to .env."))

    for path, label in (
        (".env", ".env"),
        ("data/inbox/sample.pdf", "data folder contents"),
        ("data/db.sqlite3", "the database file"),
    ):
        ignored = is_ignored(base_dir, path)
        if ignored is None:
            results.append((WARN, f"Could not run git to confirm {label} is ignored."))
        elif ignored:
            results.append((OK, f".gitignore covers {label}."))
        else:
            results.append((FAIL, f".gitignore does not cover {label}."))

    return results
