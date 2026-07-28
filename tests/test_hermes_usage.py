import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


SESSION_SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    model TEXT,
    started_at REAL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL,
    actual_cost_usd REAL
)
"""

USAGE_SCHEMA = """
CREATE TABLE {table} (
    session_id TEXT NOT NULL,
    model TEXT NOT NULL,
    billing_provider TEXT NOT NULL DEFAULT '',
    billing_base_url TEXT NOT NULL DEFAULT '',
    billing_mode TEXT NOT NULL DEFAULT '',
    task TEXT DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    actual_cost_usd REAL,
    first_seen REAL,
    last_seen REAL
)
"""


class HermesUsageTests(unittest.TestCase):
    def setUp(self):
        self.timestamp = datetime.now().astimezone().timestamp()

    def scan(self, db_path):
        cache = {"v": USAGE._SCAN_CACHE_VERSION}
        with mock.patch.object(USAGE, "_hermes_db_paths", return_value=[str(db_path)]):
            return USAGE.scan_hermes(USAGE.range_bounds(), cache)["ranges"]

    def test_sessions_only_database_keeps_legacy_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.db"
            connection = sqlite3.connect(db_path)
            connection.execute(SESSION_SCHEMA)
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("legacy", "legacy-model", self.timestamp, 100, 20, 30, 4, 5, 1.25, None),
            )
            connection.commit()
            connection.close()

            ranges = self.scan(db_path)

        self.assertEqual(ranges["today"]["in"], 100)
        self.assertEqual(ranges["today"]["out"], 20)
        self.assertEqual(ranges["today"]["cr"], 30)
        self.assertEqual(ranges["today"]["reason"], 5)
        self.assertEqual(ranges["today"]["sessions"], 1)
        self.assertEqual(ranges["today"]["cost"], 1.25)

    def test_v22_usage_includes_auxiliary_tasks_without_double_counting_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.db"
            connection = sqlite3.connect(db_path)
            connection.execute(SESSION_SCHEMA)
            connection.execute(USAGE_SCHEMA.format(table="session_model_usage"))
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("active", "main-model", self.timestamp, 100, 20, 0, 0, 3, 1.25, None),
            )
            connection.executemany(
                """INSERT INTO session_model_usage
                   (session_id, model, task, input_tokens, output_tokens, reasoning_tokens,
                    first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    ("active", "main-model", "", 100, 20, 3, self.timestamp, self.timestamp),
                    ("active", "helper-model", "approval", 12, 4, 0, self.timestamp, self.timestamp),
                    ("active", "helper-model", "title_generation", 8, 1, 0, self.timestamp, self.timestamp),
                ],
            )
            connection.commit()
            connection.close()

            ranges = self.scan(db_path)

        self.assertEqual(ranges["today"]["in"], 120)
        self.assertEqual(ranges["today"]["out"], 25)
        self.assertEqual(ranges["today"]["reason"], 3)
        self.assertEqual(ranges["today"]["sessions"], 1)
        self.assertEqual(ranges["today"]["cost"], 1.25)
        self.assertEqual(ranges["today"]["models"]["main-model"]["in"], 100)
        self.assertEqual(ranges["today"]["models"]["helper-model"]["in"], 20)

    def test_partial_v22_migration_merges_legacy_orphans_and_current_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.db"
            connection = sqlite3.connect(db_path)
            connection.execute(SESSION_SCHEMA)
            connection.execute(USAGE_SCHEMA.format(table="session_model_usage_v21"))
            connection.execute(USAGE_SCHEMA.format(table="session_model_usage"))
            connection.executemany(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("legacy-valid", "legacy", self.timestamp, 100, 10, 0, 0, 0, 0, None),
                    ("current", "current", self.timestamp, 200, 20, 0, 0, 0, 0, None),
                ],
            )
            connection.executemany(
                """INSERT INTO session_model_usage_v21
                   (session_id, model, task, input_tokens, output_tokens, first_seen, last_seen)
                   VALUES (?, ?, '', ?, ?, ?, ?)""",
                [
                    ("legacy-valid", "legacy", 100, 10, self.timestamp, self.timestamp),
                    ("deleted-history", "old-model", 300, 30, self.timestamp, self.timestamp),
                ],
            )
            connection.executemany(
                """INSERT INTO session_model_usage
                   (session_id, model, task, input_tokens, output_tokens, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    ("current", "current", "", 200, 20, self.timestamp, self.timestamp),
                    ("current", "helper", "approval", 10, 2, self.timestamp, self.timestamp),
                ],
            )
            connection.commit()
            connection.close()

            ranges = self.scan(db_path)

        self.assertEqual(ranges["today"]["in"], 610)
        self.assertEqual(ranges["today"]["out"], 62)
        self.assertEqual(ranges["today"]["sessions"], 2)

    def test_duplicate_legacy_and_current_rows_use_larger_cumulative_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.db"
            connection = sqlite3.connect(db_path)
            connection.execute(SESSION_SCHEMA)
            connection.execute(USAGE_SCHEMA.format(table="session_model_usage_v21"))
            connection.execute(USAGE_SCHEMA.format(table="session_model_usage"))
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("same", "model", self.timestamp, 120, 12, 0, 0, 0, 0, None),
            )
            for table, inp, out in (
                ("session_model_usage_v21", 100, 10),
                ("session_model_usage", 120, 12),
            ):
                connection.execute(
                    f"""INSERT INTO {table}
                        (session_id, model, task, input_tokens, output_tokens, first_seen, last_seen)
                        VALUES (?, ?, '', ?, ?, ?, ?)""",
                    ("same", "model", inp, out, self.timestamp, self.timestamp),
                )
            connection.commit()
            connection.close()

            ranges = self.scan(db_path)

        self.assertEqual(ranges["today"]["in"], 120)
        self.assertEqual(ranges["today"]["out"], 12)
        self.assertEqual(ranges["today"]["sessions"], 1)


if __name__ == "__main__":
    unittest.main()
