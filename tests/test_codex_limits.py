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
    def setUp(self):
        self.patchers = [
            mock.patch.object(USAGE, "_codex_is_custom_provider", return_value=False),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

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


class CodexCustomProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_path = Path(self.tmp.name) / "config.toml"
        self.quota_cache_path = Path(self.tmp.name) / "quota_cache.json"
        self.reset_cards_cache_path = Path(self.tmp.name) / "reset_cards_cache.json"
        self.auth_path = Path(self.tmp.name) / "auth.json"
        self.auth_path.write_text(json.dumps({
            "tokens": {"access_token": "test-token", "account_id": "test-account"}
        }))
        self.patchers = [
            mock.patch.object(USAGE, "CODEX_CONFIG", str(self.config_path)),
            mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(self.quota_cache_path)),
            mock.patch.object(USAGE, "CODEX_RESET_CARDS_CACHE", str(self.reset_cards_cache_path)),
            mock.patch.object(USAGE, "CODEX_AUTH", str(self.auth_path)),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write_config(self, text):
        self.config_path.write_text(text)

    def test_is_custom_provider_with_explicit_custom(self):
        self._write_config('model_provider = "custom"\nmodel = "deepseek-v4-flash"\n')
        self.assertTrue(USAGE._codex_is_custom_provider())

    def test_is_not_custom_provider_with_openai(self):
        self._write_config('model_provider = "openai"\nmodel = "gpt-5.5"\n')
        self.assertFalse(USAGE._codex_is_custom_provider())

    def test_is_not_custom_provider_without_config(self):
        self.assertFalse(USAGE._codex_is_custom_provider())

    def test_live_quota_skipped_for_custom_provider(self):
        self._write_config('model_provider = "custom"\n')
        # Pre-populate a stale official cache to prove it gets cleared.
        self.quota_cache_path.write_text(json.dumps({
            "fetched_at": 1_785_000_000,
            "limits": {"primary": {"used_percent": 80.0}},
            "plan": "pro",
        }))
        opener = mock.Mock(side_effect=AssertionError("should not call API"))
        with mock.patch("urllib.request.urlopen", opener):
            self.assertIsNone(USAGE.fetch_codex_live_limits())
        self.assertFalse(self.quota_cache_path.exists())

    def test_reset_cards_skipped_for_custom_provider(self):
        self._write_config('model_provider = "custom"\n')
        self.reset_cards_cache_path.write_text(json.dumps({
            "account_key": "x", "auth_key": "y", "cards": {"count": 1, "expires": [], "updated": 0}
        }))
        opener = mock.Mock(side_effect=AssertionError("should not call API"))
        with mock.patch("urllib.request.urlopen", opener):
            self.assertEqual(USAGE.fetch_codex_reset_cards(now_epoch=1_785_000_000), {})
        self.assertFalse(self.reset_cards_cache_path.exists())

    def test_iter_records_parses_token_count_with_ordinal_field(self):
        """Custom-provider Codex logs insert an 'ordinal' field between timestamp and type."""
        session_path = Path(self.tmp.name) / "rollout-ordinal.jsonl"
        session_path.write_text(json.dumps({
            "timestamp": "2026-08-07T08:00:01.000Z",
            "ordinal": 0,
            "type": "session_meta",
            "payload": {"model": "deepseek-v4-flash"}
        }) + "\n" + json.dumps({
            "timestamp": "2026-08-07T08:00:04.000Z",
            "ordinal": 18,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 1000,
                        "cached_input_tokens": 800,
                        "output_tokens": 200,
                        "reasoning_output_tokens": 50,
                    }
                }
            }
        }) + "\n")
        records = list(USAGE._iter_codex_usage_records(str(session_path)))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], ("model", "deepseek-v4-flash"))
        self.assertEqual(records[1][0], "token")


if __name__ == "__main__":
    unittest.main()
