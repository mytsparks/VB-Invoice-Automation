import base64

import anthropic

from config.secrets import Secret
from extraction.adapter import (
    ExtractorAuthError,
    ExtractorError,
    ExtractorRefused,
    ExtractorResponse,
    Usage,
)
from extraction.prompts import CURRENT_PROMPT, load_prompt
from extraction.schema import ExtractionResult

MAX_OUTPUT_TOKENS = 16000
USER_INSTRUCTION = "Extract the data from the attached document following your instructions."


class ClaudeExtractor:
    """Sends the file to the Claude API and returns the raw JSON text."""

    def __init__(self, api_key: Secret, model: str, prompt_version: str = CURRENT_PROMPT):
        self.model = model
        self.prompt_version = prompt_version
        self._system = load_prompt(prompt_version)
        # The SDK already retries connection errors, 429 and 5xx with backoff.
        self._client = anthropic.Anthropic(api_key=api_key.reveal(), max_retries=2, timeout=300.0)
        self._schema = anthropic.transform_schema(ExtractionResult)

    def extract(self, data: bytes, media_type: str) -> ExtractorResponse:
        block_type = "document" if media_type == "application/pdf" else "image"
        file_block = {
            "type": block_type,
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(data).decode("ascii"),
            },
        }
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=self._system,
                messages=[{"role": "user", "content": [file_block, {"type": "text", "text": USER_INSTRUCTION}]}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": self._schema}},
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise ExtractorAuthError(f"The API rejected the key ({exc.status_code}).") from exc
        except anthropic.APIStatusError as exc:
            raise ExtractorError(f"API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractorError("Could not reach the API. Check the network connection.") from exc

        if response.stop_reason == "refusal":
            raise ExtractorRefused("The model declined to process this document.")
        text = "".join(block.text for block in response.content if block.type == "text")
        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_input_tokens or 0,
            cache_write_tokens=response.usage.cache_creation_input_tokens or 0,
        )
        return ExtractorResponse(raw_text=text, usage=usage, request_id=getattr(response, "_request_id", "") or "")
