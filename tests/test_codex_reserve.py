import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def _ts(dt):
    return dt.astimezone().isoformat()


def _token_count_line(ts, last, total, rl):
    return json.dumps({
        "timestamp": ts,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {"last_token_usage": last, "total_token_usage": total},
            "rate_limits": rl,
        },
    })


def _turn_context_line(ts, model):
    return json.dumps({
        "timestamp": ts,
        "type": "turn_context",
        "payload": {"model": model},
    })


def _usage(inp, cached, out, reason=0):
    return {"input_tokens": inp, "cached_input_tokens": cached,
            "cache_write_input_tokens": 0, "output_tokens": out,
            "reasoning_output_tokens": reason, "total_tokens": inp + out}


def _main_rl():
    return {"limit_id": "codex", "limit_name": None,
            "primary": {"used_percent": 50.0, "window_minutes": 10080,
                        "resets_at": 1790118835},
            "plan_type": "plus"}


def _reserve_rl():
    return {"limit_id": "base_model_inference", "limit_name": "gpt-reserve",
            "primary": {"used_percent": 10.0, "window_minutes": 10080,
                        "resets_at": 1790174743},
            "plan_type": "plus"}


def _write_rollout(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class CodexLunaReserveTests(unittest.TestCase):
    def _make_files(self, root):
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        ts = _ts(now)
        main_file = Path(root) / "sessions" / "rollout-main.jsonl"
        _write_rollout(main_file, [
            _turn_context_line(ts, "gpt-5.6-luna"),
            _token_count_line(ts, _usage(20000, 15000, 500),
                              _usage(20000, 15000, 500), _main_rl()),
        ])
        reserve_file = Path(root) / "sessions" / "rollout-reserve.jsonl"
        _write_rollout(reserve_file, [
            _turn_context_line(ts, "gpt-reserve"),
            _token_count_line(ts, _usage(10000, 9000, 200),
                              _usage(10000, 9000, 200), _reserve_rl()),
        ])
        mixed_file = Path(root) / "sessions" / "rollout-mixed.jsonl"
        _write_rollout(mixed_file, [
            _turn_context_line(ts, "gpt-5.6-luna"),
            _token_count_line(ts, _usage(30000, 20000, 300),
                              _usage(30000, 20000, 300), _main_rl()),
            _token_count_line(ts, _usage(5000, 4500, 100),
                              _usage(35000, 24500, 400), _reserve_rl()),
        ])
        return now

    def _scan(self, root):
        with mock.patch.object(USAGE, "CODEX_DIR", str(Path(root) / "sessions")), \
             mock.patch.object(USAGE, "_codex_rollout_files",
                               wraps=USAGE._codex_rollout_files) as _:
            pass
        old_dir = USAGE.CODEX_DIR
        old_rollout = USAGE._codex_rollout_files
        import glob as _glob
        USAGE.CODEX_DIR = str(Path(root) / "sessions")

        def _files():
            return sorted(str(p) for p in Path(root, "sessions").glob("*.jsonl"))
        USAGE._codex_rollout_files = _files
        cache = {"v": USAGE._SCAN_CACHE_VERSION}
        try:
            with mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                result = USAGE.scan_codex(USAGE.range_bounds(), cache)
        finally:
            USAGE.CODEX_DIR = old_dir
            USAGE._codex_rollout_files = old_rollout
        return result, cache

    def test_reserve_split_from_main_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_files(tmp)
            result, _ = self._scan(tmp)

        main = result["ranges"]["all"]
        self.assertEqual(main["in"], 50000)
        self.assertEqual(main["cached"], 35000)
        self.assertEqual(main["out"], 800)
        self.assertNotIn("gpt-reserve", main["models"])
        self.assertNotIn("GPT", {m for m in main["models"]})

        reserve = result["reserve_ranges"]["all"]
        self.assertEqual(reserve["in"], 15000)
        self.assertEqual(reserve["cached"], 13500)
        self.assertEqual(reserve["out"], 300)
        self.assertEqual(set(reserve["models"]), {"gpt-reserve"})

        quota = result["reserve_quota"]
        self.assertIsNotNone(quota)
        self.assertEqual(quota["used_percent"], 10.0)
        self.assertEqual(quota["resets_at"], 1790174743)

    def test_reserve_cost_uses_luna_pricing(self):
        luna = USAGE._codex_estimated_cost("gpt-5.6-luna", 1000, 900, 100)
        reserve = USAGE._codex_estimated_cost("gpt-reserve", 1000, 900, 100)
        gpt55 = USAGE._codex_estimated_cost("openai/gpt-5.5", 1000, 900, 100)
        self.assertAlmostEqual(reserve, luna, places=9)
        self.assertLess(reserve, gpt55 / 10)

    def test_reserve_helpers(self):
        self.assertTrue(USAGE._codex_is_reserve_model("gpt-reserve"))
        self.assertTrue(USAGE._codex_is_reserve_model("GPT-Reserve"))
        self.assertFalse(USAGE._codex_is_reserve_model("gpt-5.6-luna"))
        self.assertFalse(USAGE._codex_is_reserve_model(None))
        self.assertTrue(USAGE._codex_is_reserve_limits(
            {"limit_id": "base_model_inference", "limit_name": "gpt-reserve"}))
        self.assertTrue(USAGE._codex_is_reserve_limits(
            {"limit_id": "base_model_inference", "limit_name": None}))
        self.assertFalse(USAGE._codex_is_reserve_limits(
            {"limit_id": "codex", "limit_name": None}))
        self.assertFalse(USAGE._codex_is_reserve_limits(None))


if __name__ == "__main__":
    unittest.main()
