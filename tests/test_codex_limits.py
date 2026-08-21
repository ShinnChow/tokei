import atexit
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "usage.30s.py"

# usage.30s.py 在导入时就把 HOME 展开成 ~/.codex、~/.tokei/ledger.json 等路径常量,
# 必须在 exec_module 之前换成沙箱,否则真实账本会把毕生用量并进 scan 结果。
_SANDBOX_HOME = tempfile.mkdtemp(prefix="tokei-test-home-")
os.environ["HOME"] = _SANDBOX_HOME
os.environ["USERPROFILE"] = _SANDBOX_HOME
atexit.register(shutil.rmtree, _SANDBOX_HOME, True)

SPEC = importlib.util.spec_from_file_location("tokei_usage", SCRIPT)
USAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(USAGE)

# ledger_reconcile 会兜底回填"仅账本有"的天,进程内缓存不清会让前一个用例的天数漏进后一个。
_TESTCASE_RUN = unittest.TestCase.run


def _run_with_clean_ledger(self, *args, **kwargs):
    USAGE._LEDGER_CACHE["data"] = None
    USAGE._LEDGER_CACHE["dirty"] = False
    return _TESTCASE_RUN(self, *args, **kwargs)


unittest.TestCase.run = _run_with_clean_ledger


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
                limits, _, _ = USAGE.fetch_codex_live_limits()

        request = opener.call_args.args[0]
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(
            request.unredirected_hdrs["Authorization"],
            "Bearer test-token",
        )
        self.assertEqual(limits["primary"]["used_percent"], 25.0)

    def test_recent_failure_uses_active_official_cache(self):
        now = USAGE.datetime.now().timestamp()
        auth = {
            "tokens": {
                "access_token": "test-token",
                "account_id": "test-account",
            },
        }
        account_key = USAGE._codex_auth_context(auth)["account_key"]
        limits = {
            "primary": {
                "used_percent": 69.0,
                "window_minutes": 10080,
                "resets_at": int(now + 3 * 24 * 3600),
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(json.dumps(auth))
            cache_path.write_text(json.dumps({
                "fetched_at": now - 3600,
                "last_failure_at": now,
                "limits": limits,
                "plan": "pro",
                "account_key": account_key,
            }))
            with mock.patch.object(USAGE, "CODEX_AUTH", str(auth_path)), \
                    mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(cache_path)), \
                    mock.patch("urllib.request.urlopen") as opener:
                cached_limits, plan, fetched_at = USAGE.fetch_codex_live_limits()

        opener.assert_not_called()
        self.assertEqual(cached_limits["primary"]["used_percent"], 69.0)
        self.assertEqual(plan, "pro")
        self.assertEqual(fetched_at, now - 3600)

    def test_recent_failure_rejects_cache_after_window_reset(self):
        now = USAGE.datetime.now().timestamp()
        auth = {
            "tokens": {
                "access_token": "test-token",
                "account_id": "test-account",
            },
        }
        account_key = USAGE._codex_auth_context(auth)["account_key"]
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(json.dumps(auth))
            cache_path.write_text(json.dumps({
                "fetched_at": now - 3600,
                "last_failure_at": now,
                "limits": {
                    "primary": {
                        "used_percent": 69.0,
                        "window_minutes": 10080,
                        "resets_at": int(now - 1),
                    },
                },
                "plan": "pro",
                "account_key": account_key,
            }))
            with mock.patch.object(USAGE, "CODEX_AUTH", str(auth_path)), \
                    mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(cache_path)):
                self.assertIsNone(USAGE.fetch_codex_live_limits())

    def test_official_cache_is_scoped_to_codex_account(self):
        now = USAGE.datetime.now().timestamp()
        auth = {
            "tokens": {
                "access_token": "test-token",
                "account_id": "current-account",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(json.dumps(auth))
            cache_path.write_text(json.dumps({
                "fetched_at": now - 3600,
                "last_failure_at": now,
                "limits": {
                    "primary": {
                        "used_percent": 69.0,
                        "window_minutes": 10080,
                        "resets_at": int(now + 3600),
                    },
                },
                "account_key": "different-account",
            }))
            with mock.patch.object(USAGE, "CODEX_AUTH", str(auth_path)), \
                    mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(cache_path)), \
                    mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
                self.assertIsNone(USAGE.fetch_codex_live_limits())

    def test_newer_local_snapshot_wins_over_stale_official_cache(self):
        self.assertFalse(USAGE._codex_live_snapshot_is_current(
            1_700_000_000, "2023-11-14T22:13:21+00:00"))
        self.assertTrue(USAGE._codex_live_snapshot_is_current(
            1_700_000_002, "2023-11-14T22:13:21+00:00"))


if __name__ == "__main__":
    unittest.main()
