"""Budget accounting against disposable SQLite databases."""

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from mcp.server.mcpserver import MCPServer
from my_mcp_agent import ledger
from my_mcp_agent.resources.telemetry import register_telemetry_resources
from my_mcp_agent.tools.budget import log_task_usage, register_budget_tools


class BudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Path(temporary.name) / 'ledger.db'
        for name, value in [('LEDGER_DB_PATH', self.db), ('DAILY_BUDGET_USD', 5.0)]:
            override = patch.object(ledger, name, value)
            override.start()
            self.addCleanup(override.stop)

    def test_empty_and_persisted_totals(self):
        self.assertEqual(ledger.get_budget_summary()['task_count'], 0)
        result = log_task_usage('programmer', 'test-model', 100, 20, '0.1')
        self.assertEqual(result['log_id'], 1)
        log_task_usage('qa', 'test-model', 10, 5, '0.2')
        result = ledger.get_budget_summary()
        self.assertEqual(result['spent_usd'], '0.3')
        self.assertEqual(result['input_tokens'], 110)
        self.assertEqual(result['output_tokens'], 25)
        self.assertEqual(result['task_count'], 2)
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM token_logs').fetchone()[0], 2)

    def test_boundary_and_exceeded_cost_is_retained(self):
        result = log_task_usage('qa', 'model', 0, 0, '5.0')
        self.assertTrue(result['budget_exhausted'])
        self.assertFalse(result['budget_exceeded'])
        with self.assertRaises(ledger.BudgetExceededError):
            log_task_usage('qa', 'model', 1, 1, '0.000001')
        result = ledger.get_budget_summary()
        self.assertEqual(result['spent_usd'], '5.000001')
        self.assertEqual(result['task_count'], 2)
        self.assertEqual(result['remaining_usd'], '0')

    def test_invalid_inputs_leave_no_rows(self):
        for cost in ('-1', 'NaN', 'Infinity', 'bad', '0.0000000000001', '1000000001'):
            with self.subTest(cost=cost), self.assertRaises(ValueError):
                log_task_usage('qa', 'model', 1, 1, cost)
        for tokens in (-1, True, 1.5, 2**63):
            with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                log_task_usage('qa', 'model', tokens, 1, '0')
        with self.assertRaises(ValueError):
            log_task_usage(' ', 'model', 1, 1, '0')
        self.assertEqual(ledger.get_budget_summary()['task_count'], 0)

    def test_utc_rollover(self):
        with patch.object(ledger, '_utc_now', return_value=datetime(2026, 11, 2, 23, 59, tzinfo=timezone.utc)):
            log_task_usage('qa', 'model', 1, 1, '1')
        with patch.object(ledger, '_utc_now', return_value=datetime(2026, 11, 3, tzinfo=timezone.utc)):
            summary = ledger.get_budget_summary()
            self.assertEqual(summary['date'], '2026-11-03')
            self.assertEqual(summary['spent_usd'], '0')
            self.assertEqual(summary['task_count'], 0)

    def test_concurrent_logging(self):
        ledger.get_budget_summary()
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _: log_task_usage('qa', 'model', 1, 1, '0.01'), range(12)))
        result = ledger.get_budget_summary()
        self.assertEqual(result['task_count'], 12)
        self.assertEqual(result['spent_usd'], '0.12')

    def test_resource_json_and_registration(self):
        class Registry:
            def __init__(self):
                self.resources = {}

            def resource(self, uri, **kwargs):
                def register(callback):
                    self.resources[uri] = callback
                    return callback
                return register
        registry = Registry()
        register_telemetry_resources(registry)
        result = json.loads(registry.resources['studio://telemetry/budget']())
        self.assertEqual(result['timezone'], 'UTC')
        self.assertEqual(result['spent_usd'], '0')
        server = MCPServer('BudgetTest')
        register_budget_tools(server)
        register_telemetry_resources(server)


if __name__ == '__main__':
    unittest.main()
