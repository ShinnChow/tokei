import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


class ZCodeMiMoCodeTests(unittest.TestCase):
    def create_zcode_db(self, path, created):
        connection = sqlite3.connect(path)
        connection.execute("""
            CREATE TABLE model_usage (
                id TEXT PRIMARY KEY, session_id TEXT, model_id TEXT,
                input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER,
                cache_creation_input_tokens INTEGER, cache_read_input_tokens INTEGER,
                started_at INTEGER, completed_at INTEGER
            )
        """)
        connection.execute(
            "INSERT INTO model_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("req-1", "z-session", "GLM-5.2", 100, 20, 5, 10, 30, created, created),
        )
        connection.commit()
        connection.close()

    def create_mimo_db(self, path, created):
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT)"
        )
        message = {
            "id": "msg-1", "sessionID": "m-session", "role": "assistant",
            "modelID": "MiMo-V2.5-Pro", "time": {"created": created},
            "tokens": {"input": 40, "output": 8, "reasoning": 2,
                       "cache": {"read": 10, "write": 5}},
            "cost": 0,
        }
        connection.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            ("msg-1", "m-session", created, json.dumps(message)),
        )
        connection.commit()
        connection.close()

    def test_sqlite_sources_split_tokens_cache_and_feed_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created = int(datetime.now().astimezone().replace(minute=0, second=0, microsecond=0).timestamp() * 1000)
            zcode_db = root / "zcode.sqlite"
            mimo_data = root / "mimo-home" / "data"
            mimo_data.mkdir(parents=True)
            mimo_db = mimo_data / "mimocode-nightly.db"
            self.create_zcode_db(zcode_db, created)
            self.create_mimo_db(mimo_db, created)

            old_zcode = USAGE.ZCODE_DB
            old_mimo = USAGE.MIMOCODE_DB
            old_home = os.environ.get("MIMOCODE_HOME")
            USAGE.ZCODE_DB = str(zcode_db)
            USAGE.MIMOCODE_DB = ""
            os.environ["MIMOCODE_HOME"] = str(root / "mimo-home")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            try:
                zcode = USAGE.scan_zcode(USAGE.range_bounds(), cache)
                mimocode = USAGE.scan_mimocode(USAGE.range_bounds(), cache)
                self.assertEqual(USAGE._mimocode_db_paths(), [str(mimo_db.resolve())])
                with mock.patch.object(USAGE, "_scan_zcode_database",
                                       side_effect=AssertionError("ZCode database was rescanned")), \
                     mock.patch.object(USAGE, "_scan_opencode_database",
                                       side_effect=AssertionError("MiMoCode database was rescanned")):
                    USAGE.scan_zcode(USAGE.range_bounds(), cache)
                    USAGE.scan_mimocode(USAGE.range_bounds(), cache)
            finally:
                USAGE.ZCODE_DB = old_zcode
                USAGE.MIMOCODE_DB = old_mimo
                if old_home is None:
                    os.environ.pop("MIMOCODE_HOME", None)
                else:
                    os.environ["MIMOCODE_HOME"] = old_home

            cache_path = root / "scan-cache.json"
            cache_path.write_text(json.dumps({
                "v": USAGE._SCAN_CACHE_VERSION,
                "zcode": cache["zcode"],
                "mimocode": cache["mimocode"],
            }), encoding="utf-8")
            old_cache = USAGE._SCAN_CACHE_FILE
            USAGE._SCAN_CACHE_FILE = str(cache_path)
            try:
                daily = USAGE.build_daily_costs("30d", refresh=False)
                wrapped = USAGE.build_wrapped("30d", refresh=False)
            finally:
                USAGE._SCAN_CACHE_FILE = old_cache

        zrange = zcode["ranges"]["all"]
        self.assertEqual(zrange["in"], 60)
        self.assertEqual(zrange["out"], 15)
        self.assertEqual(zrange["reason"], 5)
        self.assertEqual(zrange["cr"], 30)
        self.assertEqual(zrange["cw"], 10)
        self.assertEqual(USAGE.token_total(zrange), 120)
        self.assertEqual(zrange["sessions"], {"z-session"})
        glm_price = USAGE._raw_price(USAGE._pricing_id("GLM-5.2"))
        expected_zcode_cost = (60 * glm_price["in"] + 20 * glm_price["out"]
                               + 30 * glm_price["cache_read"] + 10 * glm_price["cache_write"]) / 1_000_000
        self.assertAlmostEqual(zrange["cost"], expected_zcode_cost, places=12)

        mrange = mimocode["ranges"]["all"]
        self.assertEqual(USAGE.token_total(mrange), 65)
        self.assertEqual(mrange["sessions"], {"m-session"})
        self.assertGreater(mrange["cost"], 0)
        self.assertEqual(daily["daily"][0]["tokens"], 185)
        self.assertIn("zcode", daily["daily"][0])
        self.assertIn("mimocode", daily["daily"][0])
        self.assertEqual({model["tool"] for model in daily["models"]}, {"zcode", "mimocode"})
        self.assertEqual(wrapped["total_tokens"], 185)
        self.assertEqual(sum(wrapped["hours"]), 185)


if __name__ == "__main__":
    unittest.main()
