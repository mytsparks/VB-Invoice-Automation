"""Blocks a commit when staged files contain what looks like a secret.

Used as the pre-commit hook. Install it with
    git config core.hooksPath .githooks
Run it by hand with
    python scripts/scan_secrets.py            (staged files)
    python scripts/scan_secrets.py file ...   (specific files)
"""
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "Generic API key assignment": re.compile(
        r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-/+]{20,}"
    ),
    "Private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
BLOCKED_NAMES = (".env", "db.sqlite3")


def staged_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def scan(paths: list[str]) -> list[str]:
    problems = []
    for name in paths:
        path = Path(name)
        if path.name in BLOCKED_NAMES or path.name.startswith(".env.") and path.name != ".env.example":
            problems.append(f"{name}: this file must never be committed")
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{name}: looks like a {label.lower()}")
    return problems


def main() -> int:
    paths = sys.argv[1:] or staged_files()
    problems = scan(paths)
    for problem in problems:
        print(f"SECRET SCAN: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
