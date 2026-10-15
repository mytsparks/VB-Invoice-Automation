import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from intake.models import Document

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@dataclass
class IngestSummary:
    added: int = 0
    duplicates: int = 0
    unsupported: int = 0


def classify_source(path: Path) -> str:
    """Only files under data/synthetic count as synthetic. Everything else is treated as real."""
    synthetic_dir = (Path(settings.BASE_DIR) / "data" / "synthetic").resolve()
    return Document.Source.SYNTHETIC if synthetic_dir in path.resolve().parents else Document.Source.REAL


def _stored_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(settings.BASE_DIR).resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def estimate_pages(data: bytes, media_type: str) -> int:
    """Rough PDF page count from the file structure. Only used for cost estimates."""
    if media_type != "application/pdf":
        return 1
    count = len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", data))
    return max(count, 1)


def ingest_folder(folder: Path, out=None) -> IngestSummary:
    """Register files from a folder. Originals are only read, never changed or moved."""
    summary = IngestSummary()
    write = out or (lambda message: None)
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and "shipments" not in p.relative_to(folder).parts):
        media_type = MEDIA_TYPES.get(path.suffix.lower())
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if Document.objects.filter(content_hash=digest).exists():
            summary.duplicates += 1
            write(f"  duplicate, skipped: {path.name}")
            continue
        if media_type is None:
            status = Document.Status.UNSUPPORTED
            summary.unsupported += 1
            write(f"  unsupported type, recorded: {path.name}")
        else:
            status = Document.Status.INGESTED
            summary.added += 1
            write(f"  added: {path.name}")
        Document.objects.create(
            path=_stored_path(path),
            file_name=path.name,
            content_hash=digest,
            size_bytes=len(data),
            media_type=media_type or (mimetypes.guess_type(path.name)[0] or ""),
            page_count=estimate_pages(data, media_type or ""),
            source=classify_source(path),
            status=status,
        )
    return summary
