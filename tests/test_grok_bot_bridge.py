import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GrokBotQuotaBridgeTests(unittest.TestCase):
    def test_electron_safe_storage_fixture(self):
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            self.skipTest("swiftc is required")
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "grok-bot-bridge-check"
            subprocess.run([
                swiftc,
                str(ROOT / "Tokei/Sources/Tokei/GrokBotQuotaBridge.swift"),
                str(ROOT / "tests/swift/GrokBotQuotaBridgeCheck.swift"),
                "-o", str(binary),
            ], check=True, capture_output=True, text=True)
            result = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True)

        self.assertEqual(result.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
