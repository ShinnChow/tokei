import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def _ts(amount):
    return amount.astimezone().isoformat()


def assistant_record(mid, model, usage, timestamp):
    return {
        "type": "message",
        "id": mid,
        "parentId": None,
        "timestamp": timestamp,
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        "usage": usage,
        "model": model,
    }


def usage_record(inp, out, cr, cw, cost):
    return {"inputTokens": inp, "outputTokens": out,
            "cacheReadTokens": cr, "cacheWriteTokens": cw, "costUsd": cost}


class CommandCodeScanTests(unittest.TestCase):
    def create_session(self, root):
        project = "/tmp/cmdcode-project"
        sid = "sess-cmd-1"
        slug = "users-tmp-cmdcode-project"
        session_file = Path(root) / "projects" / slug / f"{sid}.jsonl"
        session_file.parent.mkdir(parents=True)
        now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
        timestamp = _ts(now)
        records = [
            {"type": "session", "id": sid, "timestamp": timestamp, "cwd": project},
            assistant_record("msg-1", "meta/muse-spark-1.3-contributor",
                             usage_record(20000, 500, 15000, 100, 0.01), timestamp),
            # 同一条 message.id 是重放,必须去重。
            assistant_record("msg-1", "meta/muse-spark-1.3-contributor",
                             usage_record(11111, 111, 0, 0, 9.99), timestamp),
            assistant_record("msg-2", "meta/muse-spark-1.3-contributor",
                             usage_record(10000, 200, 1000, 50, 0.005), timestamp),
            # user 消息没有用量,不能计入。
            {"type": "message", "id": "msg-user", "timestamp": timestamp,
             "message": {"role": "user", "content": "hi"}},
        ]
        session_file.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n{broken\n",
            encoding="utf-8",
        )
        return session_file, now, project, sid

    def scan(self, root, cache=None):
        old_root = USAGE.CMDCODE_DIR
        USAGE.CMDCODE_DIR = str(root)
        scan_cache = cache if cache is not None else {"v": USAGE._SCAN_CACHE_VERSION}
        try:
            result = USAGE.scan_cmdcode(USAGE.range_bounds(), scan_cache)
        finally:
            USAGE.CMDCODE_DIR = old_root
        return result, scan_cache

    def test_assistant_usage_splits_cache_and_dedupes_replays(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_file, now, project, sid = self.create_session(tmp)
            result, cache = self.scan(tmp)

            with mock.patch.object(
                USAGE, "_scan_cmdcode_session",
                side_effect=AssertionError("unchanged session was rescanned"),
            ):
                self.scan(tmp, cache=cache)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 14000)
        self.assertEqual(usage["out"], 700)
        self.assertEqual(usage["cr"], 16000)
        self.assertEqual(usage["cw"], 150)
        self.assertEqual(USAGE.token_total(usage), 30850)
        self.assertEqual(usage["sessions"], {sid})
        self.assertAlmostEqual(usage["cost"], 0.015, places=9)
        models = usage["models"]
        self.assertEqual(set(models), {"meta/muse-spark-1.3-contributor"})
        self.assertEqual(models["meta/muse-spark-1.3-contributor"]["in"], 14000)
        self.assertAlmostEqual(models["meta/muse-spark-1.3-contributor"]["cost"], 0.015, places=9)
        entry = cache["cmdcode"][str(session_file)]
        self.assertEqual(entry["sid"], sid)
        self.assertEqual(entry["proj"], project)
        self.assertEqual(entry["parser_version"], USAGE._CMDCODE_PARSER_VERSION)
        self.assertEqual(entry["days"][now.date().isoformat()]["hours"][now.hour],
                         30850)

    def test_missing_source_clears_stale_cache(self):
        stale = {
            "v": USAGE._SCAN_CACHE_VERSION,
            "cmdcode": {"/old/session.jsonl": {"sig": "old", "days": {}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            result, cache = self.scan(tmp, cache=stale)

        self.assertEqual(result["ranges"]["all"]["in"], 0)
        self.assertEqual(cache["cmdcode"], {})
        self.assertTrue(cache["_dirty"])

    def test_utc_zulu_timestamp_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid = "sess-zulu"
            session_file = Path(tmp) / "projects" / "slug" / f"{sid}.jsonl"
            session_file.parent.mkdir(parents=True)
            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            session_file.write_text("\n".join(json.dumps(record) for record in [
                {"type": "session", "id": sid,
                 "timestamp": now.isoformat().replace("+00:00", "Z"),
                 "cwd": "/tmp/zulu-project"},
                assistant_record(
                    "msg-z", "meta/muse-spark-1.3-contributor",
                    usage_record(2000, 100, 500, 10, 0.001),
                    now.isoformat().replace("+00:00", "Z")),
            ]) + "\n", encoding="utf-8")
            result, cache = self.scan(tmp)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 1500)
        self.assertEqual(usage["cr"], 500)
        self.assertEqual(usage["sessions"], {sid})
        self.assertEqual(cache["cmdcode"][str(session_file)]["proj"], "/tmp/zulu-project")


if __name__ == "__main__":
    unittest.main()
