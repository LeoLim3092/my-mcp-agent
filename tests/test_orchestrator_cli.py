"""Offline CLI pipeline/status smoke test with temporary server and ledger paths."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_role_stdio import BOOTSTRAP

from my_mcp_agent.config import PROJECT_ROOT


class OrchestratorCLITests(unittest.TestCase):
    def test_offline_demo_and_status_are_real_stdio_and_do_not_write_game_files(self):
        with tempfile.TemporaryDirectory(prefix="studio-cli-") as directory:
            root = Path(directory)
            script = "\n".join(
                [
                    "import sys",
                    "from pathlib import Path",
                    "from my_mcp_agent import config",
                    f"config.ALLOWED_WORKSPACE = Path({str(root / 'game')!r})",
                    f"config.LEDGER_DB_PATH = Path({str(root / 'ledger.db')!r})",
                    "from my_mcp_agent.client import StdioConnection as Connection",
                    "from my_mcp_agent import orchestrator as app",
                    f"app.StdioConnection = lambda **kwargs: Connection(command=sys.executable, args=('-c', {BOOTSTRAP!r}, {str(root / 'game')!r}, {str(root / 'ledger.db')!r}, 'qa', 'normal'))",
                    "app.main()",
                ]
            )
            demo = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    "--demo",
                    "--role",
                    "qa",
                    "--task-id",
                    "offline_demo",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            self.assertIn("Task ID: offline_demo", demo.stderr)
            result = json.loads(demo.stdout)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["steps"], 2)
            self.assertEqual(list((root / "game").iterdir()), [])
            status = subprocess.run(
                [sys.executable, "-c", script, "--status", "offline_demo"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            metadata = json.loads(status.stdout)
            self.assertEqual(metadata["state"], "completed")
            self.assertEqual(len(metadata["requests"]), 2)
            self.assertTrue(
                all(item["state"] == "settled" for item in metadata["requests"])
            )
