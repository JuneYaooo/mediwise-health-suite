from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMBER = ROOT / "mediwise-health-tracker" / "scripts" / "member.py"
SETUP = ROOT / "mediwise-health-tracker" / "scripts" / "setup.py"


class BackupRestoreRoundTripTests(unittest.TestCase):
    def _run_json(self, script: Path, *args: str, env: dict) -> dict:
        completed = subprocess.run(
            [sys.executable, str(script), *args],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        if completed.returncode != 0:
            self.fail(
                f"command failed ({completed.returncode}): {completed.stdout}\n{completed.stderr}"
            )
        return json.loads(completed.stdout)

    def test_backup_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            data_dir = root / "data"
            archive = root / "backup.tar.gz"
            env = {
                **os.environ,
                "MEDIWISE_DATA_DIR": str(data_dir),
                "MEDIWISE_SINGLE_USER": "1",
            }

            first = self._run_json(
                MEMBER, "add", "--name", "原始成员", "--relation", "本人", env=env
            )
            self.assertEqual(first["status"], "ok")
            backup = self._run_json(SETUP, "backup", "--output", str(archive), env=env)
            self.assertEqual(backup["status"], "ok")
            self.assertTrue(archive.is_file())
            self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)

            self._run_json(MEMBER, "add", "--name", "临时成员", "--relation", "其他", env=env)
            before = self._run_json(MEMBER, "list", env=env)
            self.assertEqual(before["count"], 2)

            restored = self._run_json(SETUP, "restore", "--input", str(archive), env=env)
            self.assertEqual(restored["status"], "ok")
            after = self._run_json(MEMBER, "list", env=env)
            self.assertEqual(after["count"], 1)
            self.assertEqual(after["members"][0]["name"], "原始成员")


if __name__ == "__main__":
    unittest.main()
