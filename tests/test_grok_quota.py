import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


class GrokQuotaTests(unittest.TestCase):
    def setUp(self):
        self.old_home = USAGE.GROK_HOME
        self.old_log = USAGE.GROK_LOG
        self.old_auth = USAGE.GROK_AUTH
        self.old_cache = USAGE.GROK_QUOTA_CACHE
        self.old_user = USAGE._USER_DIR

    def tearDown(self):
        USAGE.GROK_HOME = self.old_home
        USAGE.GROK_LOG = self.old_log
        USAGE.GROK_AUTH = self.old_auth
        USAGE.GROK_QUOTA_CACHE = self.old_cache
        USAGE._USER_DIR = self.old_user

    def configure(self, root):
        USAGE.GROK_HOME = str(root / ".grok")
        USAGE.GROK_LOG = str(root / ".grok" / "logs" / "unified.jsonl")
        USAGE.GROK_AUTH = str(root / ".grok" / "auth.json")
        USAGE.GROK_QUOTA_CACHE = str(root / ".tokei" / "grok_quota_cache.json")
        USAGE._USER_DIR = str(root / ".tokei")
        Path(USAGE._USER_DIR).mkdir(parents=True, exist_ok=True)

    def billing_line(self, pct, start, end, plan="SuperGrok", products=None, ts=None):
        config = {
            "creditUsagePercent": pct,
            "currentPeriod": {
                "type": "USAGE_PERIOD_TYPE_WEEKLY",
                "start": start,
                "end": end,
            },
            "billingPeriodStart": start,
            "billingPeriodEnd": end,
        }
        if products is not None:
            config["productUsage"] = products
        return {
            "ts": ts or start,
            "msg": "billing: fetched credits config",
            "ctx": {"config": config, "subscriptionTier": plan},
        }

    def test_local_log_is_preferred_and_live_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            write_jsonl(Path(USAGE.GROK_LOG), [
                self.billing_line(
                    44.0,
                    "2026-07-14T08:24:06+00:00",
                    "2026-07-21T08:24:06+00:00",
                    ts="2026-07-19T02:00:00+00:00",
                ),
            ])
            with mock.patch.object(USAGE, "fetch_grok_live_quota") as live:
                quota = USAGE.scan_grok_quota()
                live.assert_not_called()

        self.assertEqual(quota["pct"], 44.0)
        self.assertEqual(quota["plan"], "SuperGrok")
        self.assertEqual(quota["source"], "log")
        self.assertEqual(quota["window"], "week")
        self.assertFalse(quota["stale"])
        self.assertIsNotNone(quota["reset"])

    def test_live_api_only_when_config_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            write_jsonl(Path(USAGE.GROK_LOG), [
                self.billing_line(
                    10.0,
                    "2026-07-14T08:24:06+00:00",
                    "2026-07-21T08:24:06+00:00",
                    ts="2026-07-19T01:00:00+00:00",
                ),
            ])
            live_payload = {
                "pct": 55.0,
                "reset": 1784622246,
                "plan": "SuperGrok",
                "products": [{"name": "GrokBuild", "pct": 50.0}],
                "window": "week",
                "source": "live",
                "updated": 1784430000,
                "stale": False,
            }
            with mock.patch.object(USAGE, "fetch_grok_live_quota", return_value=live_payload):
                quota = USAGE.scan_grok_quota()

        self.assertEqual(quota["pct"], 55.0)
        self.assertEqual(quota["source"], "live")
        self.assertEqual(quota["products"][0]["name"], "GrokBuild")

    def test_env_zero_forces_offline_even_if_config_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            write_jsonl(Path(USAGE.GROK_LOG), [
                self.billing_line(
                    12.0,
                    "2026-07-14T08:24:06+00:00",
                    "2026-07-21T08:24:06+00:00",
                    ts="2026-07-19T01:00:00+00:00",
                ),
            ])
            with mock.patch.dict(USAGE.os.environ, {"TOKEI_GROK_LIVE_QUOTA": "0"}), \
                 mock.patch.object(USAGE, "fetch_grok_live_quota") as live:
                self.assertFalse(USAGE._grok_live_quota_enabled())
                quota = USAGE.scan_grok_quota()
                live.assert_not_called()

        self.assertEqual(quota["source"], "log")
        self.assertEqual(quota["pct"], 12.0)

    def test_normalize_marks_expired_period_stale(self):
        # 2020-01-01 的 epoch 约 1577836800；用更大 now 判定已过期。
        quota = USAGE._normalize_grok_billing(
            {
                "creditUsagePercent": 80.0,
                "currentPeriod": {
                    "type": "USAGE_PERIOD_TYPE_WEEKLY",
                    "end": "2020-01-01T00:00:00+00:00",
                },
                "productUsage": [{"product": "GrokBuild", "usagePercent": 70.0}],
            },
            plan="SuperGrok",
            source="log",
            updated=1_700_000_000,
            now_epoch=1_700_000_000,
        )
        self.assertTrue(quota["stale"])
        self.assertEqual(quota["pct"], 0.0)
        self.assertIsNone(quota["reset"])
        self.assertEqual(quota["products"][0]["pct"], 0.0)

    def test_live_fetch_uses_auth_and_writes_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            Path(USAGE.GROK_AUTH).parent.mkdir(parents=True, exist_ok=True)
            Path(USAGE.GROK_AUTH).write_text(json.dumps({
                "https://auth.x.ai::id": {"key": "test-token", "auth_mode": "oidc"},
            }), encoding="utf-8")

            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return json.dumps({
                        "config": {
                            "creditUsagePercent": 33.0,
                            "currentPeriod": {
                                "type": "USAGE_PERIOD_TYPE_WEEKLY",
                                "start": "2026-07-14T08:24:06+00:00",
                                "end": "2026-07-21T08:24:06+00:00",
                            },
                            "productUsage": [
                                {"product": "GrokBuild", "usagePercent": 30.0},
                                {"product": "Api", "usagePercent": 3.0},
                            ],
                        }
                    }).encode("utf-8")

            with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as opener:
                quota = USAGE.fetch_grok_live_quota()

            self.assertEqual(opener.call_count, 1)
            req = opener.call_args[0][0]
            self.assertEqual(req.full_url, USAGE._GROK_LIVE_BILLING_URL)
            self.assertEqual(req.get_header("Authorization"), "Bearer test-token")
            self.assertEqual(quota["pct"], 33.0)
            self.assertEqual(quota["source"], "live")
            cached = json.loads(Path(USAGE.GROK_QUOTA_CACHE).read_text(encoding="utf-8"))
            self.assertEqual(cached["quota"]["pct"], 33.0)


if __name__ == "__main__":
    unittest.main()
