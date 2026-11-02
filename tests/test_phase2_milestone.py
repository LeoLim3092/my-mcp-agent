"""Phase 2.4 MCP resource checks; real hardware and a disposable ledger.

Run: .venv/bin/python -m unittest discover -s tests -p 'test_phase2_milestone.py' -v
This checks MCP dispatch directly, not Inspector or a transport connection.
"""

import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from mcp.server.mcpserver import MCPServer

from my_mcp_agent import ledger
from my_mcp_agent.resources.telemetry import register_telemetry_resources
from my_mcp_agent.tools.budget import register_budget_tools


class Phase2MilestoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_resources_and_usage_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="phase2-milestone-") as directory:
            with (
                patch.object(ledger, "LEDGER_DB_PATH", Path(directory) / "ledger.db"),
                patch.object(ledger, "DAILY_BUDGET_USD", 5.0),
            ):
                server = MCPServer("Phase2Milestone")
                register_telemetry_resources(server)
                register_budget_tools(server)

                async def read_json(uri):
                    contents = list(await asyncio.wait_for(server.read_resource(uri), timeout=10))
                    self.assertEqual(len(contents), 1)
                    self.assertEqual(contents[0].mime_type, "application/json")
                    return json.loads(contents[0].content)

                listed = {str(resource.uri): resource for resource in await server.list_resources()}
                for uri in ("studio://telemetry/hardware", "studio://telemetry/budget"):
                    self.assertIn(uri, listed)
                    self.assertEqual(listed[uri].mime_type, "application/json")

                hardware = await read_json("studio://telemetry/hardware")
                first_time = datetime.fromisoformat(hardware["timestamp_utc"])
                self.assertIsNotNone(first_time.tzinfo)
                self.assertGreaterEqual(hardware["cpu"]["usage_percent"], 0)
                self.assertLessEqual(hardware["cpu"]["usage_percent"], 100)
                self.assertGreater(hardware["memory"]["total_bytes"], 0)
                self.assertGreaterEqual(hardware["memory"]["available_bytes"], 0)
                self.assertLessEqual(hardware["memory"]["available_bytes"],
                                     hardware["memory"]["total_bytes"])
                for disk in hardware["disks"].values():
                    if disk["available"]:
                        self.assertGreater(disk["total_bytes"], 0)
                        self.assertGreaterEqual(disk["free_bytes"], 0)
                        self.assertLessEqual(disk["free_bytes"], disk["total_bytes"])
                    else:
                        self.assertIn("reason", disk)
                refreshed = await read_json("studio://telemetry/hardware")
                self.assertGreater(datetime.fromisoformat(refreshed["timestamp_utc"]), first_time)

                empty = await read_json("studio://telemetry/budget")
                self.assertEqual(empty["task_count"], 0)
                self.assertEqual(Decimal(empty["spent_usd"]), 0)
                result = await asyncio.wait_for(server.call_tool("log_task_usage", {
                    "agent_role": "milestone-test", "model": "fake-model",
                    "input_tokens": 100, "output_tokens": 25, "cost_usd": "0.125",
                }), timeout=10)
                self.assertFalse(result.is_error, str(result))
                budget = await read_json("studio://telemetry/budget")
                self.assertEqual(budget["timezone"], "UTC")
                self.assertEqual(budget["task_count"], 1)
                self.assertEqual(budget["input_tokens"], 100)
                self.assertEqual(budget["output_tokens"], 25)
                self.assertEqual(Decimal(budget["spent_usd"]), Decimal("0.125"))
                self.assertEqual(Decimal(budget["remaining_usd"]), Decimal("4.875"))
                self.assertFalse(budget["budget_exceeded"])
                self.assertFalse(budget["budget_exhausted"])

                # A separately registered server reads the same persisted ledger.
                restarted = MCPServer("Phase2Restart")
                register_telemetry_resources(restarted)
                contents = list(await asyncio.wait_for(
                    restarted.read_resource("studio://telemetry/budget"), timeout=10))
                self.assertEqual(json.loads(contents[0].content), budget)


if __name__ == "__main__":
    unittest.main(verbosity=2)
