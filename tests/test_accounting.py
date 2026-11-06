"""Durable reservations, idempotent settlement, migration, and recovery."""

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from my_mcp_agent import accounting, ledger


class AccountingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "ledger.db"
        for name, value in (("LEDGER_DB_PATH", self.path), ("DAILY_BUDGET_USD", 1.0)):
            override = patch.object(ledger, name, value)
            override.start()
            self.addCleanup(override.stop)

    def reserve(self, identity="request", amount="0.6"):
        accounting.reserve(identity, "task", "qa", "fake-model", amount, "fingerprint")

    def test_settlement_is_exact_and_idempotent(self):
        self.reserve()
        self.assertEqual(ledger.get_budget_summary()["available_usd"], "0.4")
        accounting.mark_sent("request")
        result = accounting.settle("request", 10, 2, "0.125")
        repeated = accounting.settle("request", 10, 2, "0.125")
        self.assertEqual(result["log_id"], repeated["log_id"])
        self.assertEqual(repeated["task_count"], 1)
        self.assertEqual(repeated["reserved_usd"], "0")
        with self.assertRaises(ValueError):
            accounting.settle("request", 10, 3, "0.125")

    def test_concurrent_reservations_cannot_overspend(self):
        def reserve(identity):
            try:
                self.reserve(identity)
                return True
            except accounting.BudgetReservationError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ("one", "two")))
        self.assertEqual(sum(results), 1)
        self.assertEqual(ledger.get_budget_summary()["reserved_usd"], "0.6")

    def test_unknown_request_carries_across_utc_rollover(self):
        with patch.object(
            ledger, "_utc_now", return_value=datetime(2026, 11, 3, 23, 59, tzinfo=UTC)
        ):
            self.reserve()
            accounting.mark_sent("request")
            accounting.mark_uncertain("request")
        with patch.object(
            ledger, "_utc_now", return_value=datetime(2026, 11, 4, tzinfo=UTC)
        ):
            self.assertEqual(ledger.get_budget_summary()["available_usd"], "0.4")
            with self.assertRaises(accounting.ReplayError):
                self.reserve()
            accounting.settle("request", 1, 1, "0.1")
            self.assertEqual(ledger.get_budget_summary()["reserved_usd"], "0")
            self.assertEqual(ledger.get_budget_summary()["spent_usd"], "0")

    def test_release_requires_explicit_operator_reconciliation(self):
        self.reserve()
        accounting.mark_sent("request")
        accounting.mark_uncertain("request")
        accounting.release_confirmed_unbilled("request")
        self.assertEqual(ledger.get_budget_summary()["available_usd"], "1.0")
        with self.assertRaises(ValueError):
            accounting.release_confirmed_unbilled("request")

    def test_task_and_tool_ids_cannot_be_replayed(self):
        accounting.start_task("task", "qa", "fake")
        with self.assertRaises(accounting.ReplayError):
            accounting.start_task("task", "qa", "fake")
        accounting.claim_tool("task", "call-hash", "read_file")
        with self.assertRaises(accounting.ReplayError):
            accounting.claim_tool("task", "call-hash", "read_file")
        accounting.audit("task", "tool_started", tool="read_file", step=1)
        status = accounting.task_status("task")
        self.assertEqual(status["tools"][0]["state"], "started")
        with self.assertRaises(ValueError):
            accounting.audit("task", "event", prompt="private text")
        self.assertNotIn("private text", json.dumps(status))

    def test_old_ledger_migration_preserves_usage(self):
        db = sqlite3.connect(self.path)
        db.execute(
            "CREATE TABLE token_logs(id INTEGER PRIMARY KEY,timestamp TEXT,agent_role TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER,cost_usd TEXT)"
        )
        db.execute(
            "INSERT INTO token_logs VALUES(1,?,?,?,?,?,?)",
            (ledger._utc_now().isoformat(), "qa", "old", 1, 1, "0.2"),
        )
        db.commit()
        db.close()
        self.assertEqual(ledger.get_budget_summary()["spent_usd"], "0.2")
        self.reserve(amount="0.5")
        accounting.mark_sent("request")
        accounting.settle("request", 1, 1, "0.1")
        self.assertEqual(ledger.get_budget_summary()["task_count"], 2)

    def test_reservation_overrun_is_saved(self):
        self.reserve(amount="0.1")
        accounting.mark_sent("request")
        result = accounting.settle("request", 1, 1, "1.1")
        self.assertTrue(result["reservation_exceeded"])
        self.assertTrue(result["budget_exceeded"])
        self.assertEqual(ledger.get_budget_summary()["spent_usd"], "1.1")
