import secrets
from pathlib import Path

from config.env import load_config

BASE_DIR = Path(__file__).resolve().parent.parent

# Validated application settings. Secrets inside are wrapped so they never print.
APP = load_config(BASE_DIR)

# The CLI prototype has no sessions or GUI, so a missing key gets a throwaway
# per-process value. Set DJANGO_SECRET_KEY before the audit GUI is built.
SECRET_KEY = APP.django_secret_key.reveal() if APP.django_secret_key else secrets.token_urlsafe(50)
DEBUG = APP.debug
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "config",
    "intake",
    "extraction",
    "matching",
    "processing",
    "reporting",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": APP.database_path,
    }
}
APP.database_path.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact": {"()": "config.logging.RedactingFilter"}},
    "formatters": {"plain": {"format": "%(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["redact"],
            "formatter": "plain",
        }
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"httpx": {"level": "WARNING"}, "httpx2": {"level": "WARNING"}},
}
