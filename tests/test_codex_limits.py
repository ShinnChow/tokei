import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "usage.30s.py"
SPEC = importlib.util.spec_from_file_location("tokei_usage", SCRIPT)
USAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(USAGE)


class _Response:
    def __init__(self, payload, url=None):
        self.payload = json.dumps(payload).encode()
        self.url = url or USAGE._CODEX_USAGE_URL

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.payload[:limit]


class CodexQuotaValuesTests(unittest.TestCase):
    def test_legacy_primary_5h_secondary_week(self):
        limits = {
            "primary": {"used_percent": 25.0, "window_minutes": 300, "resets_at": 200},
            "secondary": {"used_percent": 40.0, "window_minutes": 10080, "resets_at": 300},
        }

        self.assertEqual(
            USAGE._codex_quota_values(limits, now_epoch=100),
            {"p5": 25.0, "pw": 40.0, "r5": 200, "rw": 300},
        )

    def test_week_only_primary(self):
        limits = {
            "primary": {"used_percent": 1.0, "window_minutes": 10080, "resets_at": 300},
            "secondary": None,
        }

        self.assertEqual(
            USAGE._codex_quota_values(limits, now_epoch=100),
            {"p5": None, "pw": 1.0, "r5": None, "rw": 300},
        )

    def test_expired_window_is_reset(self):
        limits = {
            "primary": {"used_percent": 90.0, "window_minutes": 10080, "resets_at": 99},
        }

        self.assertEqual(
            USAGE._codex_quota_values(limits, now_epoch=100),
            {"p5": None, "pw": 0.0, "r5": None, "rw": None},
        )

    def test_live_quota_rejects_cross_origin_redirect(self):
        payload = {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 25,
                    "limit_window_seconds": 604800,
                    "reset_at": 200,
                },
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            cache_path = Path(temp_dir) / "cache.json"
            auth_path.write_text(json.dumps({
                "tokens": {
                    "access_token": "test-token",
                    "account_id": "test-account",
                },
            }))
            response = _Response(payload, url="https://example.com/usage")
            with mock.patch.object(USAGE, "CODEX_AUTH", str(auth_path)), \
                    mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(cache_path)), \
                    mock.patch("urllib.request.urlopen", return_value=response):
                self.assertIsNone(USAGE.fetch_codex_live_limits())

    def test_live_quota_uses_initial_request_only_credentials(self):
        payload = {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 25,
                    "limit_window_seconds": 604800,
                    "reset_at": 200,
                },
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            cache_path = Path(temp_dir) / "cache.json"
            auth_path.write_text(json.dumps({
                "tokens": {
                    "access_token": "test-token",
                    "account_id": "test-account",
                },
            }))
            opener = mock.Mock(return_value=_Response(payload))
            with mock.patch.object(USAGE, "CODEX_AUTH", str(auth_path)), \
                    mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(cache_path)), \
                    mock.patch("urllib.request.urlopen", opener):
                limits, _ = USAGE.fetch_codex_live_limits()

        request = opener.call_args.args[0]
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(
            request.unredirected_hdrs["Authorization"],
            "Bearer test-token",
        )
        self.assertEqual(limits["primary"]["used_percent"], 25.0)


if __name__ == "__main__":
    unittest.main()
