import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class PrimeAgentUsageTests(unittest.TestCase):
    def write_session(self, path, session_id, project, messages):
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [{"type": "session", "version": 3, "id": session_id,
                    "timestamp": "2026-08-06T09:00:00Z", "cwd": project}, *messages]
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    def assistant(self, timestamp, model="gpt-5.6-sol", stop_reason="stop", **usage):
        return {"type": "message", "timestamp": timestamp,
                "message": {"role": "assistant", "provider": "metarouter", "model": model,
                             "stopReason": stop_reason, "usage": {
                                 "input": usage.get("input", 0), "output": usage.get("output", 0),
                                 "cacheRead": usage.get("cache_read", 0), "cacheWrite": usage.get("cache_write", 0),
                                 "cost": usage.get("cost", {})}}}

    def scan(self, agent_dir):
        with mock.patch.object(USAGE, "PRIME_AGENT_DIR", str(agent_dir)), \
             mock.patch.dict(os.environ, {}, clear=False):
            for key in ("TOKEI_PRIME_AGENT_SESSION_DIR", "PRIME_AGENT_SESSION_DIR",
                        "PRIME_AGENT_CODING_AGENT_SESSION_DIR", "PRIME_AGENT_CODING_AGENT_DIR"):
                os.environ.pop(key, None)
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            return USAGE.scan_prime_agent(USAGE.range_bounds(), cache), cache

    def test_root_and_nested_children_are_counted_without_attribution_double_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent_dir = Path(tmp) / ".prime" / "agent"
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()
            root_message = self.assistant(now, input=100, output=20, cache_read=30,
                                          cache_write=4, cost={"total": 0.42})
            root_message["id"] = "root-assistant"
            attributed = {"type": "child_usage_attributed", "timestamp": now,
                          "targetId": "root-assistant", "childUsage": {
                              "input": 50, "output": 10, "cacheRead": 5, "cacheWrite": 1,
                              "cost": {"total": 0.2}}}
            self.write_session(agent_dir / "sessions" / "root.jsonl", "root", "/tmp/root-project",
                               [root_message, attributed])
            self.write_session(agent_dir / "sessions" / "root-copy.jsonl", "root", "/tmp/root-project",
                               [root_message, attributed])
            self.write_session(agent_dir / "session-artifacts" / "root" / "sub-a" / "child.jsonl",
                               "child", "/tmp/child-project",
                               [self.assistant(now, input=50, output=10, cache_read=5, cache_write=1,
                                                cost={"input": 0.1, "output": 0.1})])
            self.write_session(agent_dir / "session-artifacts" / "root" / "sub-a" /
                               "session-artifacts" / "child" / "sub-b" / "grandchild.jsonl",
                               "grandchild", "/tmp/grandchild-project",
                               [self.assistant(now, stop_reason="error", input=25, output=5,
                                                cache_read=2, cost={"total": 0.08})])
            result, cache = self.scan(agent_dir)
        usage = result["ranges"]["all"]
        self.assertEqual((usage["in"], usage["out"], usage["cr"], usage["cw"]), (175, 35, 37, 5))
        self.assertEqual(usage["sessions"], {"root", "child", "grandchild"})
        self.assertAlmostEqual(usage["cost"], 0.70)
        self.assertEqual(len(cache["prime_agent"]), 3)

    def test_model_project_and_unchanged_cache_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent_dir = Path(tmp) / "agent"
            session = agent_dir / "sessions" / "session.jsonl"
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()
            self.write_session(session, "session-id", "/tmp/prime-project",
                               [self.assistant(now, input=10, output=2, cost={"total": 0.12})])
            with mock.patch.object(USAGE, "PRIME_AGENT_DIR", str(agent_dir)), \
                 mock.patch.dict(os.environ, {}, clear=False):
                for key in ("TOKEI_PRIME_AGENT_SESSION_DIR", "PRIME_AGENT_SESSION_DIR",
                            "PRIME_AGENT_CODING_AGENT_SESSION_DIR", "PRIME_AGENT_CODING_AGENT_DIR"):
                    os.environ.pop(key, None)
                cache = {"v": USAGE._SCAN_CACHE_VERSION}
                first = USAGE.scan_prime_agent(USAGE.range_bounds(), cache)
                cache["_dirty"] = False
                with mock.patch.object(USAGE, "_parse_prime_session_file",
                                       side_effect=AssertionError("reparsed")):
                    second = USAGE.scan_prime_agent(USAGE.range_bounds(), cache)
        self.assertEqual(first, second)
        self.assertEqual(cache["prime_agent"][str(session.resolve())]["proj"], "/tmp/prime-project")
        self.assertIn("metarouter/gpt-5.6-sol", first["ranges"]["all"]["models"])
        self.assertFalse(cache["_dirty"])

    def test_explicit_session_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); default_dir = root / "agent"; override = root / "custom-sessions"
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()
            self.write_session(override / "custom.jsonl", "custom", "/tmp/custom",
                               [self.assistant(now, input=7, output=3, cost={"total": 0.01})])
            with mock.patch.object(USAGE, "PRIME_AGENT_DIR", str(default_dir)), \
                 mock.patch.dict(os.environ, {"TOKEI_PRIME_AGENT_SESSION_DIR": str(override)}):
                result = USAGE.scan_prime_agent(USAGE.range_bounds(), {"v": USAGE._SCAN_CACHE_VERSION})
        self.assertEqual(result["ranges"]["all"]["in"], 7)
        self.assertEqual(result["ranges"]["all"]["sessions"], {"custom"})


if __name__ == "__main__":
    unittest.main()
