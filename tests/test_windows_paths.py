import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


class WindowsPathDiscoveryTests(unittest.TestCase):
    def test_configured_candidates_are_expanded_prioritized_and_deduped(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            configured = os.pathsep.join((str(first), str(second), str(first)))
            with mock.patch.dict(os.environ, {
                "TOKEI_TEST_ROOT": tmp,
                "TOKEI_TEST_PATHS": configured,
            }):
                paths = USAGE._path_candidates(
                    "TOKEI_TEST_PATHS", "$TOKEI_TEST_ROOT/second")

        self.assertEqual(paths, [os.path.abspath(first), os.path.abspath(second)])

    def test_appdata_candidates_feed_each_supported_discovery_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roaming = root / "AppData" / "Roaming"
            local = root / "AppData" / "Local"

            gemini_root = roaming / "Gemini" / "conversations"
            gemini_file = gemini_root / "project" / "chats" / "session-win.json"
            gemini_file.parent.mkdir(parents=True)
            gemini_file.write_text("{}", encoding="utf-8")

            opencode_data = roaming / "opencode"
            opencode_db = opencode_data / "opencode.db"
            opencode_messages = opencode_data / "storage" / "message"
            opencode_messages.mkdir(parents=True)
            opencode_db.write_bytes(b"sqlite")

            qoder_db = roaming / "QoderWork" / "data" / "agents.db"
            qoder_ide_db = roaming / "Qoder" / "SharedClientCache" / "cache" / "db" / "local.db"
            qoder_db.parent.mkdir(parents=True)
            qoder_ide_db.parent.mkdir(parents=True)
            qoder_db.write_bytes(b"sqlite")
            qoder_ide_db.write_bytes(b"sqlite")

            claude_cache = roaming / "Claude" / "Cache" / "Cache_Data"
            claude_cache.mkdir(parents=True)
            cache_file = claude_cache / "entry_0"
            cache_file.write_bytes(b"cache")

            env = {
                "TOKEI_GEMINI_DIR": "",
                "TOKEI_OPENCODE_DATA_DIR": "",
                "TOKEI_OPENCODE_DIR": "",
                "TOKEI_QODER_DB": "",
                "TOKEI_QODER_IDE_DB": "",
                "TOKEI_CLAUDE_CACHE_DIR": "",
                "MIMOCODE_HOME": "",
                "XDG_DATA_HOME": "",
            }
            with mock.patch.dict(os.environ, env), \
                 mock.patch.object(USAGE, "GEMINI_DIR", str(root / "missing-gemini")), \
                 mock.patch.object(USAGE, "GEMINI_DIRS", [str(gemini_root)]), \
                 mock.patch.object(USAGE, "OPENCODE_DATA_DIR", str(root / "missing-opencode")), \
                 mock.patch.object(USAGE, "OPENCODE_DATA_DIRS", [str(opencode_data)]), \
                 mock.patch.object(USAGE, "OPENCODE_DB", str(root / "missing.db")), \
                 mock.patch.object(USAGE, "OPENCODE_DIR", str(root / "missing-messages")), \
                 mock.patch.object(USAGE, "_QODER_DB", str(root / "missing-qoder.db")), \
                 mock.patch.object(USAGE, "QODER_DB_PATHS", [str(qoder_db)]), \
                 mock.patch.object(USAGE, "QODER_IDE_DB", str(root / "missing-qoder-ide.db")), \
                 mock.patch.object(USAGE, "QODER_IDE_DB_PATHS", [str(qoder_ide_db)]), \
                 mock.patch.object(USAGE, "CLAUDE_CACHE", str(root / "missing-cache")), \
                 mock.patch.object(USAGE, "CLAUDE_CACHE_DIRS", [str(claude_cache)]), \
                 mock.patch.object(USAGE, "APPDATA", str(roaming)), \
                 mock.patch.object(USAGE, "LOCALAPPDATA", str(local)):
                self.assertEqual(USAGE._gemini_session_files(), [str(gemini_file.resolve())])
                self.assertEqual(USAGE._opencode_db_paths(), [str(opencode_db.resolve())])
                self.assertEqual(USAGE._opencode_json_dirs(), [str(opencode_messages.resolve())])
                self.assertEqual(USAGE._qoder_db_path(), str(qoder_db))
                self.assertEqual(USAGE._qoder_ide_db_path(), str(qoder_ide_db))
                self.assertEqual(USAGE._claude_cache_files(), [str(cache_file.resolve())])
                with mock.patch.object(USAGE.os, "name", "nt"):
                    self.assertEqual(USAGE._mimocode_data_dirs()[0], str(local / "mimocode"))


if __name__ == "__main__":
    unittest.main()
