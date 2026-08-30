import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class PricingCacheTests(unittest.TestCase):
    @staticmethod
    def response(prompt="0.000001"):
        return io.BytesIO(json.dumps({
            "data": [{
                "id": "test/model",
                "name": "Test Model",
                "canonical_slug": "test/model-2026",
                "owned_by": "test-owner",
                "pricing": {
                    "prompt": prompt,
                    "completion": "0.000002",
                    "input_cache_read": "0.0000005",
                    "input_cache_write": "0.0000008",
                },
            }],
        }).encode("utf-8"))

    def test_unchanged_price_update_keeps_token_scan_cache(self):
        existing_models = {
            "test/model": {
                "in": 1.0,
                "out": 2.0,
                "cache_read": 0.5,
                "cache_write": 0.8,
                "name": "Test Model",
                "canonical_slug": "test/model-2026",
                "owned_by": "test-owner",
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            pricing = Path(tmp) / "pricing.json"
            scan_cache = Path(tmp) / "scan-cache.json"
            pricing.write_text(json.dumps({"models": existing_models}), encoding="utf-8")
            scan_cache.write_text(json.dumps({
                "v": USAGE._SCAN_CACHE_VERSION,
                "sentinel": True,
            }), encoding="utf-8")

            with mock.patch("urllib.request.urlopen", return_value=self.response()), \
                 mock.patch.object(USAGE, "PRICING_FILE", str(pricing)), \
                 mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache)), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(USAGE.update_prices(), 0)

            self.assertTrue(scan_cache.exists())
            self.assertTrue(json.loads(scan_cache.read_text(encoding="utf-8"))["sentinel"])
            saved = json.loads(pricing.read_text(encoding="utf-8"))["models"]["test/model"]
            self.assertEqual(saved["name"], "Test Model")
            self.assertEqual(saved["canonical_slug"], "test/model-2026")
            self.assertEqual(saved["owned_by"], "test-owner")

    def test_changed_price_update_invalidates_cost_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            pricing = Path(tmp) / "pricing.json"
            scan_cache = Path(tmp) / "scan-cache.json"
            pricing.write_text(json.dumps({"models": {
                "test/model": {"in": 1.0, "out": 2.0, "cache_read": 0.5, "cache_write": 0.8},
            }}), encoding="utf-8")
            scan_cache.write_text(json.dumps({"v": USAGE._SCAN_CACHE_VERSION}), encoding="utf-8")

            with mock.patch("urllib.request.urlopen", return_value=self.response("0.000003")), \
                 mock.patch.object(USAGE, "PRICING_FILE", str(pricing)), \
                 mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache)), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(USAGE.update_prices(), 0)

            self.assertFalse(scan_cache.exists())


if __name__ == "__main__":
    unittest.main()
