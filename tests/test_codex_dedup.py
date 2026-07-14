import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def event(ts, day, total, last, cost):
    return [ts, day, *total, *last, cost]


class CodexDedupedDaysTests(unittest.TestCase):
    def test_replayed_parent_snapshot_is_counted_once(self):
        parent = event(
            "2026-07-10T00:00:00+00:00",
            "2026-07-10",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            1.0,
        )
        replay = event(
            "2026-07-10T01:00:00+00:00",
            "2026-07-10",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            1.0,
        )
        child_increment = event(
            "2026-07-10T01:01:00+00:00",
            "2026-07-10",
            (150, 120, 8, 3),
            (50, 40, 3, 1),
            0.5,
        )

        days = USAGE._codex_deduped_days({
            "child": {"session_id": "child", "forked_from_id": "parent",
                      "events": [replay, child_increment]},
            "parent": {"session_id": "parent", "events": [parent]},
        })

        self.assertEqual(days["parent"]["2026-07-10"]["in"], 100)
        self.assertEqual(days["child"]["2026-07-10"]["in"], 50)
        self.assertEqual(days["child"]["2026-07-10"]["out"], 3)
        parent_hour = datetime.fromisoformat(parent[0]).astimezone().hour
        child_hour = datetime.fromisoformat(child_increment[0]).astimezone().hour
        self.assertEqual(days["parent"]["2026-07-10"]["hours"][parent_hour], 105)
        self.assertEqual(days["child"]["2026-07-10"]["hours"][child_hour], 53)

    def test_matching_snapshots_in_independent_sessions_are_kept(self):
        first = event(
            "2026-07-10T00:00:00+00:00",
            "2026-07-10",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            1.0,
        )
        second = event(
            "2026-07-10T01:00:00+00:00",
            "2026-07-10",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            1.0,
        )

        days = USAGE._codex_deduped_days({
            "a": {"session_id": "a", "events": [first]},
            "b": {"session_id": "b", "events": [second]},
        })

        self.assertEqual(days["a"]["2026-07-10"]["in"], 100)
        self.assertEqual(days["b"]["2026-07-10"]["in"], 100)

    def test_events_without_cumulative_total_are_kept(self):
        first = event(
            "2026-07-10T00:00:00+00:00",
            "2026-07-10",
            (None, None, None, None),
            (25, 20, 2, 1),
            0.1,
        )
        second = event(
            "2026-07-10T00:01:00+00:00",
            "2026-07-10",
            (None, None, None, None),
            (25, 20, 2, 1),
            0.1,
        )

        days = USAGE._codex_deduped_days({
            "a": {"events": [first]},
            "b": {"events": [second]},
        })

        self.assertEqual(days["a"]["2026-07-10"]["in"], 25)
        self.assertEqual(days["b"]["2026-07-10"]["in"], 25)


class CodexScanDedupTests(unittest.TestCase):
    def session_meta(self, sid, forked_from_id=None):
        payload = {
            "session_id": forked_from_id or sid,
            "id": sid,
            "cwd": "/tmp/project",
            "model_provider": "custom",
        }
        if forked_from_id:
            payload["forked_from_id"] = forked_from_id
        return json.dumps({
            "timestamp": "2024-01-08T00:00:00Z",
            "type": "session_meta",
            "payload": payload,
        })

    def test_session_meta_prefers_own_id_over_parent_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-child.jsonl"
            path.write_text(self.session_meta("child", "parent") + "\n", encoding="utf-8")
            session_id, parent_id = USAGE._codex_session_meta(path)

        self.assertEqual(session_id, "child")
        self.assertEqual(parent_id, "parent")

    def test_session_meta_reads_legacy_nested_parent_id(self):
        meta = {
            "timestamp": "2024-01-08T00:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "child",
                "source": {
                    "subagent": {
                        "thread_spawn": {"parent_thread_id": "parent"},
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-child.jsonl"
            path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
            session_id, parent_id = USAGE._codex_session_meta(path)

        self.assertEqual(session_id, "child")
        self.assertEqual(parent_id, "parent")

    def token_count(self, ts, total, last):
        return json.dumps({
            "timestamp": ts,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": total[0],
                        "cached_input_tokens": total[1],
                        "output_tokens": total[2],
                        "reasoning_output_tokens": total[3],
                    },
                    "last_token_usage": {
                        "input_tokens": last[0],
                        "cached_input_tokens": last[1],
                        "output_tokens": last[2],
                        "reasoning_output_tokens": last[3],
                    },
                },
            },
        })

    def turn_context(self, ts, model):
        return json.dumps({
            "timestamp": ts,
            "type": "turn_context",
            "payload": {"model": model, "cwd": "/tmp/project"},
        })

    def test_scan_attributes_each_increment_to_the_active_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-models.jsonl"
            path.write_text("\n".join([
                self.session_meta("models"),
                self.turn_context("2024-01-08T00:00:00Z", "gpt-5.4"),
                self.token_count("2024-01-08T00:01:00Z", (100, 80, 10, 4), (100, 80, 10, 4)),
                self.turn_context("2024-01-08T00:02:00Z", "gpt-5.5"),
                self.token_count("2024-01-08T00:03:00Z", (150, 120, 15, 6), (50, 40, 5, 2)),
            ]) + "\n", encoding="utf-8")
            day = datetime(2024, 1, 8, tzinfo=timezone.utc)
            bounds = {
                "today": day, "yesterday": day - timedelta(days=1), "week": day,
                "last_week": day - timedelta(days=7), "last_week_end": day,
                "month": day.replace(day=1), "year": day.replace(month=1, day=1),
            }
            old_dir = USAGE.CODEX_DIR
            USAGE.CODEX_DIR = tmp
            try:
                with mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                    result = USAGE.scan_codex(bounds, {"v": USAGE._SCAN_CACHE_VERSION})
            finally:
                USAGE.CODEX_DIR = old_dir

        models = result["ranges"]["all"]["models"]
        self.assertEqual(models["openai/gpt-5.4"]["in"], 20)
        self.assertEqual(models["openai/gpt-5.4"]["cr"], 80)
        self.assertEqual(models["openai/gpt-5.4"]["out"], 10)
        self.assertEqual(models["openai/gpt-5.4"]["reason"], 4)
        self.assertEqual(models["openai/gpt-5.5"]["in"], 10)
        self.assertEqual(models["openai/gpt-5.5"]["cr"], 40)

    def test_scan_keeps_child_increment_and_drops_replayed_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "rollout-parent.jsonl"
            child = root / "rollout-child.jsonl"
            inherited_total = (100, 80, 5, 2)
            child_total = (150, 120, 8, 3)
            child_last = (50, 40, 3, 1)
            parent.write_text(
                "\n".join([
                    self.session_meta("parent"),
                    self.token_count("2024-01-08T00:00:00Z", inherited_total, inherited_total),
                ]) + "\n",
                encoding="utf-8",
            )
            child.write_text(
                "\n".join([
                    self.session_meta("child", "parent"),
                    self.token_count("2024-01-08T01:00:00Z", inherited_total, inherited_total),
                    self.token_count("2024-01-08T01:01:00Z", child_total, child_last),
                ]) + "\n",
                encoding="utf-8",
            )
            day = datetime(2024, 1, 8, tzinfo=timezone.utc)
            bounds = {
                "today": day,
                "yesterday": day - timedelta(days=1),
                "week": day,
                "last_week": day - timedelta(days=7),
                "last_week_end": day,
                "month": day.replace(day=1),
                "year": day.replace(month=1, day=1),
            }
            old_dir = USAGE.CODEX_DIR
            USAGE.CODEX_DIR = tmp
            try:
                result = USAGE.scan_codex(bounds, {"v": USAGE._SCAN_CACHE_VERSION})
            finally:
                USAGE.CODEX_DIR = old_dir

        all_usage = result["ranges"]["all"]
        self.assertEqual(all_usage["in"], 150)
        self.assertEqual(all_usage["cached"], 120)
        self.assertEqual(all_usage["out"], 8)
        self.assertEqual(all_usage["reason"], 3)
        self.assertEqual(len(all_usage["sessions"]), 2)

    def test_scan_keeps_independent_sessions_with_same_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "rollout-first.jsonl"
            second = root / "rollout-second.jsonl"
            usage = (100, 80, 5, 2)
            first.write_text(
                "\n".join([
                    self.session_meta("first"),
                    self.token_count("2024-01-08T00:00:00Z", usage, usage),
                ]) + "\n",
                encoding="utf-8",
            )
            second.write_text(
                "\n".join([
                    self.session_meta("second"),
                    self.token_count("2024-01-08T01:00:00Z", usage, usage),
                ]) + "\n",
                encoding="utf-8",
            )
            day = datetime(2024, 1, 8, tzinfo=timezone.utc)
            bounds = {
                "today": day,
                "yesterday": day - timedelta(days=1),
                "week": day,
                "last_week": day - timedelta(days=7),
                "last_week_end": day,
                "month": day.replace(day=1),
                "year": day.replace(month=1, day=1),
            }
            old_dir = USAGE.CODEX_DIR
            USAGE.CODEX_DIR = tmp
            try:
                result = USAGE.scan_codex(bounds, {"v": USAGE._SCAN_CACHE_VERSION})
            finally:
                USAGE.CODEX_DIR = old_dir

        all_usage = result["ranges"]["all"]
        self.assertEqual(all_usage["in"], 200)
        self.assertEqual(all_usage["cached"], 160)
        self.assertEqual(all_usage["out"], 10)
        self.assertEqual(all_usage["reason"], 4)
        self.assertEqual(len(all_usage["sessions"]), 2)


class ScanCacheMigrationTests(unittest.TestCase):
    def test_v13_cache_is_invalidated_for_session_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan-cache.json"
            path.write_text(json.dumps({"v": 13, "codex": {"stale": {}}}), encoding="utf-8")
            old_path = USAGE._SCAN_CACHE_FILE
            USAGE._SCAN_CACHE_FILE = str(path)
            try:
                cache = USAGE._load_scan_cache()
            finally:
                USAGE._SCAN_CACHE_FILE = old_path

        self.assertEqual(cache["v"], USAGE._SCAN_CACHE_VERSION)
        self.assertTrue(cache["_dirty"])
        self.assertNotIn("codex", cache)


class CodexTokenLineReaderTests(unittest.TestCase):
    def test_skips_large_unrelated_record_and_handles_chunk_boundaries(self):
        token = json.dumps({
            "timestamp": "2026-07-13T01:02:03Z",
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {}},
        }).encode()
        unrelated = (
            b'{"timestamp":"2026-07-13T01:02:02Z","type":"response_item",'
            b'"payload":{"content":"mentions \\"token_count\\" '
            + b"x" * (2 * 1024 * 1024)
            + b'"}}\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-large.jsonl"
            path.write_bytes(unrelated + token)
            lines = list(USAGE._iter_codex_token_lines(
                path, chunk_size=17, header_limit=512
            ))

        self.assertEqual(lines, [token])

    def test_accepts_compact_json(self):
        token = json.dumps({
            "timestamp": "2026-07-13T01:02:03Z",
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {}},
        }, separators=(",", ":")).encode()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-compact.jsonl"
            path.write_bytes(token + b"\n")
            lines = list(USAGE._iter_codex_token_lines(path, chunk_size=11))

        self.assertEqual(lines, [token])

    def test_extracts_model_without_buffering_following_large_content(self):
        context = (
            b'{"timestamp":"2026-07-13T01:02:02Z","type":"turn_context",'
            b'"payload":{"model":"gpt-5.4","instructions":"' + b"x" * (2 * 1024 * 1024) + b'"}}\n'
        )
        token = json.dumps({
            "timestamp": "2026-07-13T01:02:03Z",
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {}},
        }, separators=(",", ":")).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-model.jsonl"
            path.write_bytes(context + token)
            records = list(USAGE._iter_codex_usage_records(path, chunk_size=19))

        self.assertEqual(records, [("model", "gpt-5.4"), ("token", token)])


if __name__ == "__main__":
    unittest.main()
