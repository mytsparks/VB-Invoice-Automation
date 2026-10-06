import logging
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from config.checks import FAIL, is_ignored, run_checks
from config.env import ConfigError, load_config, require_llm_key
from config.logging import RedactingFilter, register_secret
from config.secrets import Secret

BASE = Path(settings.BASE_DIR)
FAKE_KEY = "sk-ant-" + "test-0123456789abcdefghij"  # split so the secret scanner does not flag it


class SecretTests(SimpleTestCase):
    def test_str_and_repr_are_masked(self):
        secret = Secret(FAKE_KEY)
        self.assertNotIn(FAKE_KEY, str(secret))
        self.assertNotIn(FAKE_KEY, repr(secret))
        self.assertNotIn(FAKE_KEY, f"{secret} {secret!r} {[secret]}")
        self.assertEqual(secret.reveal(), FAKE_KEY)

    def test_log_filter_redacts_registered_secret(self):
        register_secret(Secret(FAKE_KEY))
        record = logging.LogRecord("t", logging.INFO, "", 0, "key was %s", (FAKE_KEY,), None)
        RedactingFilter().filter(record)
        self.assertNotIn(FAKE_KEY, record.getMessage())

    def test_config_repr_does_not_leak_key(self):
        config = load_config(BASE, {"ANTHROPIC_API_KEY": FAKE_KEY})
        self.assertNotIn(FAKE_KEY, repr(config))


class SettingsTests(SimpleTestCase):
    def test_defaults_need_no_credentials(self):
        config = load_config(BASE, {})
        self.assertIsNone(config.anthropic_api_key)
        self.assertEqual(config.tms_mode, "mock")
        self.assertFalse(config.allow_real_invoices_to_llm)

    def test_placeholder_key_counts_as_missing(self):
        for value in ("", "your-key-here", "sk-ant-xxxxxxxxxxxxxxxx", "<paste key>"):
            config = load_config(BASE, {"ANTHROPIC_API_KEY": value})
            with self.assertRaises(ConfigError):
                require_llm_key(config)

    def test_bad_number_is_a_clear_error(self):
        with self.assertRaises(ConfigError):
            load_config(BASE, {"LLM_RUN_COST_CAP_USD": "five"})

    def test_missing_key_fails_only_when_llm_required(self):
        config = load_config(BASE, {})
        self.assertFalse(any(level == FAIL for level, _ in run_checks(config, BASE)))
        self.assertTrue(any(level == FAIL for level, _ in run_checks(config, BASE, require_llm=True)))

    def test_unsupported_tms_mode_fails(self):
        config = load_config(BASE, {"TMS_MODE": "sandbox"})
        self.assertTrue(any(level == FAIL for level, _ in run_checks(config, BASE)))


class GitignoreTests(SimpleTestCase):
    def check(self, path):
        result = is_ignored(BASE, path)
        if result is None:
            self.skipTest("git is not available")
        return result

    def test_sensitive_paths_are_ignored(self):
        for path in (".env", "data/inbox/a.pdf", "data/some_invoice.pdf", "data/db.sqlite3", "data/ground_truth/x.csv"):
            self.assertTrue(self.check(path), path)

    def test_safe_paths_are_not_ignored(self):
        for path in ("data/README.md", "data/synthetic/a.pdf", ".env.example"):
            self.assertFalse(self.check(path), path)
