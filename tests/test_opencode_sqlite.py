import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def assistant(message_id, session_id, created, input_tokens, output_tokens=0,
              cost=0.25, model_id="claude-sonnet-4.6"):
    return {
        "id": message_id,
        "sessionID": session_id,
        "role": "assistant",
        "modelID": model_id,
        "time": {"created": created},
        "tokens": {
            "input": input_tokens,
            "output": output_tokens,
            "reasoning": 3,
            "cache": {"read": 4, "write": 5},
        },
        "cost": cost,
    }


class OpenCodeSqliteTests(unittest.TestCase):
    def test_database_is_cached_and_preferred_over_duplicate_legacy_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "opencode"
            legacy = root / "storage" / "message" / "ses_legacy"
            legacy.mkdir(parents=True)
            db_path = root / "opencode.db"
            created = int(datetime.now().astimezone().timestamp() * 1000)

            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT)"
            )
            connection.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?)",
                ("msg-db", "ses-db", created, json.dumps(assistant("msg-db", "ses-db", created, 100, 10))),
            )
            connection.commit()
            connection.close()

            (legacy / "msg_db.json").write_text(
                json.dumps(assistant("msg-db", "ses-legacy", created, 999, 99)), encoding="utf-8")
            (legacy / "msg_file.json").write_text(
                json.dumps(assistant("msg-file", "ses-legacy", created, 50, 5)), encoding="utf-8")

            old_db = USAGE.OPENCODE_DB
            old_dir = USAGE.OPENCODE_DIR
            USAGE.OPENCODE_DB = str(db_path)
            USAGE.OPENCODE_DIR = str(root / "storage" / "message")
            try:
                cache = {"v": USAGE._SCAN_CACHE_VERSION}
                result = USAGE.scan_opencode(USAGE.range_bounds(), cache)
                with mock.patch.object(
                    USAGE, "_scan_opencode_database",
                    side_effect=AssertionError("unchanged SQLite database was rescanned"),
                ):
                    cached = USAGE.scan_opencode(USAGE.range_bounds(), cache)
            finally:
                USAGE.OPENCODE_DB = old_db
                USAGE.OPENCODE_DIR = old_dir

            cache_path = Path(tmp) / "scan-cache.json"
            cache_path.write_text(json.dumps({
                "v": USAGE._SCAN_CACHE_VERSION,
                "opencode": cache["opencode"],
            }), encoding="utf-8")
            old_cache = USAGE._SCAN_CACHE_FILE
            USAGE._SCAN_CACHE_FILE = str(cache_path)
            try:
                daily = USAGE.build_daily_costs("30d", refresh=False)
                wrapped = USAGE.build_wrapped("30d", refresh=False)
            finally:
                USAGE._SCAN_CACHE_FILE = old_cache

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 150)
        self.assertEqual(usage["out"], 15)
        self.assertEqual(usage["cr"], 8)
        self.assertEqual(usage["cw"], 10)
        self.assertEqual(usage["reason"], 6)
        self.assertEqual(usage["cost"], 0.5)
        self.assertEqual(usage["sessions"], {"ses-db", "ses-legacy"})
        self.assertEqual(cached["ranges"]["all"]["in"], 150)
        self.assertEqual(len(daily["daily"]), 1)
        self.assertEqual(daily["daily"][0]["tokens"], 189)
        self.assertEqual(wrapped["total_tokens"], 189)
        self.assertEqual(sum(wrapped["hours"]), 189)

    def test_zero_cost_uses_pricing_fallback_and_refreshes_old_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "opencode.db"
            created = int(datetime.now().astimezone().timestamp() * 1000)
            message = assistant(
                "msg-zero-cost",
                "ses-zero-cost",
                created,
                1_000_000,
                100_000,
                cost=0,
                model_id="glm-5.2",
            )

            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT)"
            )
            connection.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?)",
                ("msg-zero-cost", "ses-zero-cost", created, json.dumps(message)),
            )
            connection.commit()
            connection.close()

            cache_key = "db:" + str(db_path)
            cache = {
                "v": USAGE._SCAN_CACHE_VERSION,
                "opencode": {
                    cache_key: {
                        "sig": USAGE._sqlite_signature(str(db_path)),
                        "days": {},
                        "message_ids": [],
                        "source": "sqlite",
                    },
                },
            }
            with mock.patch.object(USAGE, "_opencode_db_paths", return_value=[str(db_path)]), \
                 mock.patch.object(USAGE, "_opencode_json_dirs", return_value=[]):
                result = USAGE.scan_opencode(USAGE.range_bounds(), cache)
                with mock.patch.object(
                    USAGE,
                    "_scan_opencode_database",
                    side_effect=AssertionError("repriced OpenCode cache was rescanned"),
                ):
                    cached = USAGE.scan_opencode(USAGE.range_bounds(), cache)

        price = USAGE._raw_price(USAGE._pricing_id("glm-5.2"))
        expected = (
            1_000_000 / 1e6 * price["in"]
            + (100_000 + 3) / 1e6 * price["out"]
            + 4 / 1e6 * price["cache_read"]
            + 5 / 1e6 * price["cache_write"]
        )
        self.assertGreater(expected, 0)
        self.assertAlmostEqual(result["ranges"]["all"]["cost"], expected)
        self.assertAlmostEqual(cached["ranges"]["all"]["cost"], expected)
        self.assertEqual(
            cache["opencode"][cache_key]["cost_version"],
            USAGE._OPENCODE_COST_CACHE_VERSION,
        )

    def test_signature_tracks_wal_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.db"
            path.write_bytes(b"db")
            first = USAGE._sqlite_signature(str(path))
            (Path(str(path) + "-wal")).write_bytes(b"wal-1")
            second = USAGE._sqlite_signature(str(path))
            (Path(str(path) + "-wal")).write_bytes(b"wal-2-longer")
            third = USAGE._sqlite_signature(str(path))

        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)

    def test_signature_ignores_shm_metadata_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.db"
            path.write_bytes(b"db")
            first = USAGE._sqlite_signature(str(path))
            shm = Path(str(path) + "-shm")
            shm.write_bytes(b"shm-1")
            second = USAGE._sqlite_signature(str(path))
            shm.write_bytes(b"shm-2-longer")
            third = USAGE._sqlite_signature(str(path))

        self.assertEqual(first, second)
        self.assertEqual(second, third)

    def test_hermes_cache_is_invalidated_by_wal_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.db"
            db_path.write_bytes(b"db")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}

            with mock.patch.object(USAGE, "_hermes_db_paths", return_value=[str(db_path)]), \
                 mock.patch.object(USAGE, "_scan_hermes_db", return_value={}) as scan:
                USAGE.scan_hermes(USAGE.range_bounds(), cache)
                USAGE.scan_hermes(USAGE.range_bounds(), cache)
                self.assertEqual(scan.call_count, 1)

                Path(str(db_path) + "-wal").write_bytes(b"new-wal-data")
                USAGE.scan_hermes(USAGE.range_bounds(), cache)
                self.assertEqual(scan.call_count, 2)

    def test_openclaw_task_cache_reads_new_wal_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runs.sqlite"
            connection = sqlite3.connect(db_path)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE task_runs (created_at INTEGER, status TEXT)")
            created = int(datetime.now().astimezone().timestamp() * 1000)
            connection.execute("INSERT INTO task_runs VALUES (?, ?)", (created, "completed"))
            connection.commit()

            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            with mock.patch.object(USAGE, "OPENCLAW_DB", str(db_path)), \
                 mock.patch.object(USAGE, "OPENCLAW_STATE_DB", str(Path(tmp) / "missing.sqlite")), \
                 mock.patch.object(USAGE, "OPENCLAW_AGENTS", str(Path(tmp) / "agents")):
                first = USAGE.scan_openclaw(USAGE.range_bounds(), cache)
                connection.execute("INSERT INTO task_runs VALUES (?, ?)", (created, "failed"))
                connection.commit()
                second = USAGE.scan_openclaw(USAGE.range_bounds(), cache)

            connection.close()

        self.assertEqual(first["ranges"]["all"]["tasks"], 1)
        self.assertEqual(second["ranges"]["all"]["tasks"], 2)
        self.assertEqual(second["ranges"]["all"]["failed"], 1)


if __name__ == "__main__":
    unittest.main()
