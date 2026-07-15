import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class UpdaterSecurityTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "Tokei updater is macOS-only")
    def test_swift_security_policy(self):
        swiftc = shutil.which("swiftc")
        self.assertIsNotNone(swiftc, "swiftc is required")

        root = Path(__file__).resolve().parents[1]
        policy = root / "Tokei" / "Sources" / "TokeiUpdateSecurity" / "UpdateSecurity.swift"
        harness = root / "tests" / "swift" / "UpdaterSecurityCheck.swift"

        with tempfile.TemporaryDirectory(prefix="tokei-updater-test-") as temp_dir:
            binary = Path(temp_dir) / "updater-security-check"
            compile_result = subprocess.run(
                [swiftc, str(policy), str(harness), "-o", str(binary)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                compile_result.stdout + compile_result.stderr,
            )

            run_result = subprocess.run(
                [str(binary)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                run_result.returncode,
                0,
                run_result.stdout + run_result.stderr,
            )
            self.assertIn("Updater security checks passed", run_result.stdout)

    def test_release_metadata_includes_dmg_sha256(self):
        root = Path(__file__).resolve().parents[1]
        generator = root / "Tokei" / "generate_update_metadata.sh"

        with tempfile.TemporaryDirectory(prefix="tokei-metadata-test-") as temp_dir:
            dmg = Path(temp_dir) / "Tokei.dmg"
            output = Path(temp_dir) / "latest.json"
            dmg.write_bytes(b"test-dmg")

            result = subprocess.run(
                ["/bin/bash", str(generator), "v1.0.14", str(dmg), str(output)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            metadata = json.loads(output.read_text())
            self.assertEqual(metadata["tag_name"], "v1.0.14")
            self.assertEqual(
                metadata["download_url"],
                "https://dl.lanshuagent.com/tokei/Tokei-v1.0.14.dmg",
            )
            self.assertEqual(metadata["sha256"], hashlib.sha256(b"test-dmg").hexdigest())


if __name__ == "__main__":
    unittest.main()
