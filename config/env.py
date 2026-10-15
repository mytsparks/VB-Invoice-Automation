"""Single place where configuration and secrets are read.

Secrets come only from environment variables or the root .env file. They are
never accepted as command line arguments.
"""
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv

from config.logging import register_secret
from config.secrets import Secret

PLACEHOLDER_PREFIXES = ("your", "paste", "replace", "changeme", "<", "example")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class AppConfig:
    anthropic_api_key: Secret | None
    claude_model: str
    allow_real_invoices_to_llm: bool
    max_docs_per_run: int
    run_cost_cap_usd: Decimal
    low_confidence_threshold: float
    tms_mode: str
    tms_fixture_dirs: tuple[Path, ...]
    tms_max_writes_per_run: int
    django_secret_key: Secret | None
    debug: bool
    database_path: Path
    data_dir: Path


def is_placeholder(value: str | None) -> bool:
    text = (value or "").strip().lower()
    return not text or text.startswith(PLACEHOLDER_PREFIXES) or "xxxx" in text


def _flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _secret(environ, name: str) -> Secret | None:
    value = environ.get(name, "").strip()
    if is_placeholder(value):
        return None
    return Secret(value)


def load_config(base_dir: Path, environ=None) -> AppConfig:
    if environ is None:
        load_dotenv(base_dir / ".env", override=False)
        environ = os.environ
    try:
        cost_cap = Decimal(environ.get("LLM_RUN_COST_CAP_USD", "5.00"))
        max_docs = int(environ.get("LLM_MAX_DOCS_PER_RUN", "25"))
        threshold = float(environ.get("LOW_CONFIDENCE_THRESHOLD", "0.85"))
        max_writes = int(environ.get("TMS_MAX_WRITES_PER_RUN", "50"))
    except (InvalidOperation, ValueError) as exc:
        raise ConfigError(f"A numeric setting in .env is not valid ({exc}).") from exc

    database_path = Path(environ.get("DATABASE_PATH", "data/db.sqlite3"))
    if not database_path.is_absolute():
        database_path = base_dir / database_path

    config = AppConfig(
        anthropic_api_key=_secret(environ, "ANTHROPIC_API_KEY"),
        claude_model=environ.get("CLAUDE_MODEL", "claude-sonnet-5-5").strip(),
        allow_real_invoices_to_llm=_flag(environ.get("ALLOW_REAL_INVOICES_TO_LLM", "false")),
        max_docs_per_run=max_docs,
        run_cost_cap_usd=cost_cap,
        low_confidence_threshold=threshold,
        tms_mode=environ.get("TMS_MODE", "mock").strip().lower(),
        tms_fixture_dirs=(base_dir / "data" / "fixtures" / "shipments", base_dir / "data" / "synthetic" / "shipments"),
        tms_max_writes_per_run=max_writes,
        django_secret_key=_secret(environ, "DJANGO_SECRET_KEY"),
        debug=_flag(environ.get("DJANGO_DEBUG", "false")),
        database_path=database_path,
        data_dir=base_dir / "data",
    )
    register_secret(config.anthropic_api_key)
    register_secret(config.django_secret_key)
    return config


def require_llm_key(config: AppConfig) -> Secret:
    if config.anthropic_api_key is None:
        raise ConfigError(
            "ANTHROPIC_API_KEY is missing or still a placeholder. "
            "Copy .env.example to .env and paste your key there."
        )
    return config.anthropic_api_key
