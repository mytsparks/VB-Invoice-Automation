from pathlib import Path

from django.conf import settings

CURRENT_PROMPT = "invoice_extraction/v2"


def load_prompt(version: str = CURRENT_PROMPT) -> str:
    """Prompts are versioned files under prompts/. The version string is recorded with every run."""
    path = Path(settings.BASE_DIR) / "prompts" / f"{version}.md"
    return path.read_text(encoding="utf-8")
