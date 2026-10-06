"""The extraction interface. Matching, review and reporting depend only on this shape,
so another extraction approach can be compared later without touching them."""
from dataclasses import dataclass
from typing import Protocol


class ExtractorRefused(Exception):
    """The model declined to answer. The document goes to human review."""


class ExtractorAuthError(Exception):
    """The key was rejected. Retrying other documents would only repeat the failure."""


class ExtractorError(Exception):
    """Any other failure calling the extractor. The message must not contain document content."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class ExtractorResponse:
    raw_text: str
    usage: Usage
    request_id: str = ""


class Extractor(Protocol):
    model: str
    prompt_version: str

    def extract(self, data: bytes, media_type: str) -> ExtractorResponse:
        """Return the raw JSON text the model produced for this document."""
        ...
