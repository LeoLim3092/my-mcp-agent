"""SQLite accounting shared by budget tools and telemetry resources.

USD amounts are stored as decimal text and summed with Decimal, never SQL REAL.
Budget days use UTC. The ledger is initialized lazily, not during module import.
"""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from my_mcp_agent.config import DAILY_BUDGET_USD, LEDGER_DB_PATH
from my_mcp_agent.contracts import BudgetSummary, UsageLogResult


class BudgetExceededError(RuntimeError):
    """Usage was recorded, but the resulting daily spend exceeds the limit."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _money(value: str | float | Decimal) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("USD amounts must be valid decimal numbers.") from error
    if not amount.is_finite() or amount < 0 or amount > Decimal(1000000000):
        raise ValueError("USD amounts must be finite and between 0 and 1 billion.")
    if amount.as_tuple().exponent < -12:
        raise ValueError("USD amounts support at most 12 decimal places.")
    return amount


@contextmanager
def _connection():
    connection = sqlite3.connect(LEDGER_DB_PATH, timeout=10)
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS token_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                agent_role TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL CHECK(input_tokens >= 0),
                output_tokens INTEGER NOT NULL CHECK(output_tokens >= 0),
                cost_usd TEXT NOT NULL
            )
        """)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS token_logs_timestamp ON token_logs(timestamp)"
        )
        connection.commit()
        yield connection
    finally:
        connection.close()


def _summary(connection, now: datetime) -> BudgetSummary:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    rows = connection.execute(
        "SELECT input_tokens, output_tokens, cost_usd FROM token_logs "
        "WHERE timestamp >= ? AND timestamp < ?",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    spent = sum((Decimal(row[2]) for row in rows), Decimal(0))
    limit = _money(DAILY_BUDGET_USD)
    return {
        "date": start.date().isoformat(),
        "timezone": "UTC",
        "spent_usd": format(spent, "f"),
        "daily_budget_usd": format(limit, "f"),
        "remaining_usd": format(max(limit - spent, Decimal(0)), "f"),
        "budget_exceeded": spent > limit,
        "budget_exhausted": spent >= limit,
        "task_count": len(rows),
        "input_tokens": sum(row[0] for row in rows),
        "output_tokens": sum(row[1] for row in rows),
    }


def get_budget_summary() -> BudgetSummary:
    """Read today's recorded usage; monetary fields are decimal USD strings."""
    with _connection() as connection:
        return _summary(connection, _utc_now())


def record_task_usage(
    agent_role: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: str,
) -> UsageLogResult:
    """Record incurred cost exactly once per invocation, even above the budget.

    No retry deduplication is provided: retrying a successful/erroring call can
    double-count usage. The caller supplies actual cost, not model price guesses.
    """
    for label, value in (("agent_role", agent_role), ("model", model)):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(f"{label} must contain 1–200 characters and not be blank.")
    for tokens in (input_tokens, output_tokens):
        if type(tokens) is not int or not 0 <= tokens <= 2**63 - 1:
            raise ValueError("Token counts must be nonnegative SQLite-range integers.")
    cost = _money(cost_usd)
    with _connection() as connection:
        # Serialize inserts and their associated daily totals across clients.
        connection.execute("BEGIN IMMEDIATE")
        now = _utc_now()
        cursor = connection.execute(
            "INSERT INTO token_logs "
            "(timestamp, agent_role, model, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                now.isoformat(),
                agent_role.strip(),
                model.strip(),
                input_tokens,
                output_tokens,
                str(cost),
            ),
        )
        summary: UsageLogResult = {
            **_summary(connection, now),
            "log_id": cursor.lastrowid,
        }
        connection.commit()
    if summary["budget_exceeded"]:
        raise BudgetExceededError(
            f"Usage recorded as log {summary['log_id']}; UTC daily spend "
            f"${summary['spent_usd']} exceeds ${summary['daily_budget_usd']}. "
            "Stop further model tasks. Do not retry this log call."
        )
    return summary
