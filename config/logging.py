import logging

from config.secrets import Secret

_registered: set[str] = set()


def register_secret(secret: Secret | None) -> None:
    """Tell the log filter about a secret so it is redacted if it ever reaches a log line."""
    if secret and len(secret.reveal()) >= 8:
        _registered.add(secret.reveal())


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for value in _registered:
            redacted = redacted.replace(value, "********")
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True
