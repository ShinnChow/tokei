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


def isolate_ledger(testcase):
    USAGE._LEDGER_CACHE.update({"data": None, "dirty": False})
    patcher = mock.patch.object(
        USAGE, "_load_ledger_from_disk",
        return_value={"v": USAGE._LEDGER_VERSION, "tools": {}})
    patcher.start()
    testcase.addCleanup(patcher.stop)


def gemini_message(message_id, input_tokens, timestamp, model="gemini-3.5-flash"):
    return {
        "id": message_id,
        "timestamp": timestamp,
        "type": "gemini",
        "model": model,
        "tokens": {"input": input_tokens, "output": 10, "cached": 5, "thoughts": 2},
    }


class GeminiUsageTests(unittest.TestCase):
    def setUp(self):
        isolate_ledger(self)
        self.old_dir = USAGE.GEMINI_DIR
        self.old_dirs = USAGE.GEMINI_DIRS

    def tearDown(self):
        USAGE.GEMINI_DIR = self.old_dir
        USAGE.GEMINI_DIRS = self.old_dirs

    def test_jsonl_updates_nested_subagents_and_migration_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            chats = Path(tmp) / "project" / "chats"
            nested = chats / "parent-session"
            nested.mkdir(parents=True)
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()

            legacy = {
                "sessionId": "main-session",
                "projectHash": "project",
                "lastUpdated": now,
                "messages": [gemini_message("legacy-msg", 500, now)],
            }
            (chats / "session-old.json").write_text(json.dumps(legacy), encoding="utf-8")

            main_records = [
                {"sessionId": "main-session", "projectHash": "project", "lastUpdated": now},
                gemini_message("main-msg", 50, now),
                gemini_message("main-msg", 150, now),
            ]
            (chats / "session-new.jsonl").write_text(
                "\n".join(json.dumps(item) for item in main_records) + "\n", encoding="utf-8")

            sub_records = [
                {"sessionId": "sub-session", "projectHash": "project", "kind": "subagent"},
                gemini_message("sub-msg", 1000, now),
            ]
            (nested / "sub-session.jsonl").write_text(
                "\n".join(json.dumps(item) for item in sub_records) + "\n", encoding="utf-8")

            USAGE.GEMINI_DIR = tmp
            USAGE.GEMINI_DIRS = [tmp]
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            result = USAGE.scan_gemini(USAGE.range_bounds(), cache)
            with mock.patch.object(
                USAGE, "_load_gemini_usage_file",
                side_effect=AssertionError("unchanged Gemini files were reparsed"),
            ):
                cached = USAGE.scan_gemini(USAGE.range_bounds(), cache)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 1150)
        self.assertEqual(usage["out"], 20)
        self.assertEqual(usage["cached"], 10)
        self.assertEqual(usage["thoughts"], 4)
        self.assertEqual(usage["sessions"], {"main-session", "sub-session"})
        self.assertEqual(cached["ranges"]["all"]["in"], 1150)
        self.assertEqual(len(cache["gemini"]), 3)
        self.assertTrue(cache["_dirty"])

    def test_rewind_and_checkpoint_follow_gemini_journal_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()
            records = [
                {"sessionId": "session", "projectHash": "project"},
                gemini_message("one", 10, now),
                gemini_message("two", 20, now),
                {"$rewindTo": "two"},
                {"$set": {"messages": [gemini_message("three", 30, now)]}},
                gemini_message("three", 40, now),
            ]
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")

            parsed = USAGE._load_gemini_usage_file(str(path))

        self.assertEqual(len(parsed["events"]), 1)
        self.assertEqual(parsed["events"][0]["id"], "three")
        self.assertEqual(parsed["events"][0]["tokens"]["input"], 40)

    def test_antigravity_sqlite_protobuf_parsing_and_scan(self):
        def encode_varint(val):
            res = bytearray()
            while True:
                b = val & 0x7F
                val >>= 7
                if val:
                    res.append(b | 0x80)
                else:
                    res.append(b)
                    break
            return bytes(res)

        def encode_proto_field(field_num, wire_type, val):
            key = (field_num << 3) | wire_type
            if wire_type == 0:
                return encode_varint(key) + encode_varint(val)
            elif wire_type == 2:
                if isinstance(val, str):
                    val = val.encode("utf-8")
                return encode_varint(key) + encode_varint(len(val)) + val
            raise NotImplementedError

        def make_gen_step(model, inp, out, cached, thoughts, ts_sec):
            tok_sub = (encode_proto_field(2, 0, inp) +
                       encode_proto_field(3, 0, out) +
                       encode_proto_field(5, 0, cached) +
                       encode_proto_field(9, 0, thoughts))
            time_sub = encode_proto_field(4, 2, encode_proto_field(1, 0, ts_sec))
            sub1 = (encode_proto_field(19, 2, model) +
                    encode_proto_field(4, 2, tok_sub) +
                    encode_proto_field(9, 2, time_sub))
            return encode_proto_field(1, 2, sub1)

        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            conv_dir = Path(tmp) / "antigravity-cli" / "conversations"
            conv_dir.mkdir(parents=True)
            db_path = conv_dir / "session-12345.db"

            now_sec = int(datetime.now().astimezone().timestamp())
            step0 = make_gen_step("gemini-3.7-flash", inp=200, out=50, cached=800, thoughts=20, ts_sec=now_sec)
            step1 = make_gen_step("gemini-3.7-flash", inp=500, out=100, cached=1200, thoughts=40, ts_sec=now_sec + 10)

            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB, size INTEGER)")
            conn.execute("INSERT INTO gen_metadata (idx, data, size) VALUES (0, ?, ?)", (step0, len(step0)))
            conn.execute("INSERT INTO gen_metadata (idx, data, size) VALUES (1, ?, ?)", (step1, len(step1)))
            conn.commit()
            conn.close()

            # Test _load_antigravity_db directly
            parsed = USAGE._load_antigravity_db(str(db_path))
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["sid"], "session-12345")
            self.assertEqual(len(parsed["events"]), 2)
            self.assertEqual(parsed["events"][0]["tokens"]["input"], 1000)  # 200 + 800 cached
            self.assertEqual(parsed["events"][0]["tokens"]["cached"], 800)
            self.assertEqual(parsed["events"][0]["tokens"]["output"], 50)
            self.assertEqual(parsed["events"][0]["tokens"]["thoughts"], 20)
            self.assertEqual(parsed["events"][1]["tokens"]["input"], 1700)  # 500 + 1200 cached

            # Test full scan_gemini integration and cache
            USAGE.GEMINI_DIR = str(conv_dir)
            USAGE.GEMINI_DIRS = [str(conv_dir)]
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            result = USAGE.scan_gemini(USAGE.range_bounds(), cache)
            with mock.patch.object(
                USAGE, "_load_antigravity_db",
                side_effect=AssertionError("unchanged Antigravity DB was reparsed"),
            ):
                cached_res = USAGE.scan_gemini(USAGE.range_bounds(), cache)

            usage = result["ranges"]["all"]
            self.assertEqual(usage["in"], 2700)  # total prompt tokens = 1000 + 1700
            self.assertEqual(usage["cached"], 2000)  # 800 + 1200
            self.assertEqual(usage["out"], 150)  # 50 + 100
            self.assertEqual(usage["thoughts"], 60)  # 20 + 40
            self.assertEqual(usage["sessions"], {"session-12345"})
            self.assertEqual(cached_res["ranges"]["all"]["in"], 2700)
            self.assertTrue(cache["_dirty"])


if __name__ == "__main__":
    unittest.main()
