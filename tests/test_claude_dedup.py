import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from test_codex_limits import USAGE


def assistant(message_id, input_tokens, output_tokens=0, request_id=None, event_id=None,
              sidechain=False, timestamp=None):
    record = {
        "type": "assistant",
        "timestamp": (timestamp or datetime.now().astimezone()).isoformat(),
        "uuid": event_id,
        "requestId": request_id,
        "isSidechain": sidechain,
        "cwd": "/tmp/claude-project",
        "message": {
            "id": message_id,
            "model": "claude-sonnet-4.6",
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        },
    }
    return record


class ClaudeDedupTests(unittest.TestCase):
    def scan(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, records in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
            old_dir = USAGE.CLAUDE_DIR
            USAGE.CLAUDE_DIR = tmp
            try:
                cache = {"v": USAGE._SCAN_CACHE_VERSION}
                result = USAGE.scan_claude(USAGE.range_bounds(), cache)
            finally:
                USAGE.CLAUDE_DIR = old_dir
        return result, cache

    def test_content_blocks_count_once_and_largest_snapshot_wins(self):
        records = [
            assistant("msg-1", 100, 10, event_id="event-thinking"),
            assistant("msg-1", 100, 10, event_id="event-text"),
            assistant("msg-1", 140, 20, event_id="event-tool"),
        ]
        result, cache = self.scan({"project/session.jsonl": records})

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 140)
        self.assertEqual(usage["out"], 20)
        self.assertEqual(len(usage["sessions"]), 1)
        events = next(iter(cache["claude"].values()))["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_id"], "event-tool")

    def test_distinct_request_ids_remain_distinct(self):
        records = [
            assistant("msg-shared", 100, request_id="request-1"),
            assistant("msg-shared", 80, request_id="request-2"),
        ]
        result, _ = self.scan({"project/session.jsonl": records})
        self.assertEqual(result["ranges"]["all"]["in"], 180)

    def test_parent_entry_replaces_sidechain_replay_across_files(self):
        timestamp = datetime.now().astimezone()
        files = {
            "project/sidechain.jsonl": [
                assistant("msg-parent", 500, request_id="side", sidechain=True, timestamp=timestamp),
            ],
            "project/parent.jsonl": [
                assistant("msg-parent", 120, request_id="parent", sidechain=False, timestamp=timestamp),
            ],
        }
        result, cache = self.scan(files)

        self.assertEqual(result["ranges"]["all"]["in"], 120)
        populated = [entry for entry in cache["claude"].values() if entry.get("days")]
        self.assertEqual(len(populated), 1)
        self.assertTrue(populated[0]["proj"].endswith("claude-project"))

    def test_uuid_dedupes_records_without_message_id(self):
        records = [
            assistant(None, 60, event_id="same-event"),
            assistant(None, 60, event_id="same-event"),
        ]
        result, _ = self.scan({"project/session.jsonl": records})
        self.assertEqual(result["ranges"]["all"]["in"], 60)


if __name__ == "__main__":
    unittest.main()
