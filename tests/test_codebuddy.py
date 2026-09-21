import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


def codebuddy_item(item_id, message_id, timestamp, input_tokens, output_tokens,
                   cached=0, credits=0.0, session_id="session-1",
                   model_id="fictional-codebuddy-model"):
    return {
        "type": "function_call",
        "id": item_id,
        "sessionId": session_id,
        "timestamp": timestamp,
        "cwd": "/tmp/codebuddy-project",
        "message": {
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "cache_read_input_tokens": cached,
            },
        },
        "providerData": {
            "messageId": message_id,
            "requestModelId": model_id,
            "requestModelName": "Fictional CodeBuddy Model",
            "usage": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": input_tokens + output_tokens,
            },
            "rawUsage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "prompt_cache_hit_tokens": cached,
                "prompt_cache_miss_tokens": input_tokens - cached,
                "prompt_cache_write_tokens": 0,
                "completion_thinking_tokens": output_tokens // 2,
                "credit": credits,
            },
        },
    }


class CodeBuddyUsageTests(unittest.TestCase):
    def test_raw_usage_and_credit_are_normalized_without_double_counting_thoughts(self):
        item = codebuddy_item(
            "entry-1", "generation-1", "2026-09-17T12:00:00+08:00",
            100, 20, cached=40, credits=1.25,
        )

        record = USAGE._workbuddy_usage_record(item, model_id_first=True)

        self.assertEqual(record["in"], 60)
        self.assertEqual(record["out"], 20)
        self.assertEqual(record["cr"], 40)
        self.assertEqual(record["cw"], 0)
        self.assertEqual(record["reason"], 0)
        self.assertAlmostEqual(record["credits"], 1.25)
        self.assertEqual(record["message_id"], "generation-1")
        self.assertEqual(record["model"], "fictional-codebuddy-model")
        self.assertEqual(USAGE.token_total(record), 120)
        self.assertEqual(record["cost"], 0)

    def test_scan_dedupes_same_generation_and_keeps_codebuddy_credits(self):
        timestamp = "2026-09-17T12:00:00+08:00"
        first = codebuddy_item(
            "entry-1", "generation-1", timestamp, 100, 20,
            cached=40, credits=1.25,
        )
        richer_replay = codebuddy_item(
            "entry-replay", "generation-1", timestamp, 120, 25,
            cached=50, credits=1.75,
        )
        second = codebuddy_item(
            "entry-2", "generation-2", "2026-09-17T12:00:01+08:00",
            80, 10, cached=20, credits=0.5,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project").mkdir()
            (root / "project" / "main.jsonl").write_text(
                "\n".join(json.dumps(item) for item in (first, second)) + "\n",
                encoding="utf-8",
            )
            (root / "project" / "replay.jsonl").write_text(
                json.dumps(richer_replay) + "\n", encoding="utf-8"
            )
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            with mock.patch.object(USAGE, "CODEBUDDY_DIR", str(root)), \
                 mock.patch.object(USAGE, "ledger_touch"), \
                 mock.patch.object(
                     USAGE, "ledger_reconcile",
                     side_effect=lambda _tool, days, _source_days=None: days,
                 ):
                result = USAGE.scan_codebuddy(USAGE.range_bounds(), cache)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 130)
        self.assertEqual(usage["cr"], 70)
        self.assertEqual(usage["out"], 35)
        self.assertAlmostEqual(usage["credits"], 2.25)
        self.assertEqual(len(usage["sessions"]), 1)
        self.assertEqual(len(list(USAGE._iter_workbuddy_records(cache["codebuddy"]))), 2)
        self.assertEqual(len(cache["codebuddy"]), 2)

    def test_dashboard_keeps_codebuddy_credits_separate_from_usd_cost(self):
        record = USAGE._workbuddy_usage_record(
            codebuddy_item(
                "entry-1", "generation-1", "2026-09-17T12:00:00+08:00",
                100, 20, cached=40, credits=1.25,
            ),
            model_id_first=True,
        )
        record["session"] = "session-1"
        record["dedup"] = "dedup-1"

        cache = {
            "v": USAGE._SCAN_CACHE_VERSION,
            "codebuddy": {
                "/tmp/codebuddy.jsonl": {
                    "records": [record],
                    "proj": "/tmp/codebuddy-project",
                },
            },
        }
        with mock.patch.object(USAGE, "_load_ledger", return_value={"tools": {}}):
            dashboard = USAGE.build_daily_costs("all", refresh=False, _cache=cache)

        row = next(item for item in dashboard["daily"] if item["date"] == "2026-09-17")
        self.assertEqual(row["codebuddy"], 0)
        self.assertEqual(row["cb_in"], 60)
        self.assertEqual(row["cb_cr"], 40)
        self.assertAlmostEqual(row["cb_credits"], 1.25)
        model = next(item for item in dashboard["models"] if item["tool"] == "codebuddy")
        self.assertAlmostEqual(model["credits"], 1.25)


if __name__ == "__main__":
    unittest.main()
