"""Trusted orchestration accounting, durable claims, and metadata-only audit logs."""

import json
import sqlite3
from decimal import Decimal

from my_mcp_agent import ledger


class BudgetReservationError(RuntimeError):
    pass


class ReplayError(RuntimeError):
    """An operation identity already exists; never replay unknown side effects."""


def start_task(task_id: str, role: str, model: str) -> None:
    with ledger._connection() as db:
        try:
            db.execute(
                "INSERT INTO task_runs(task_id,timestamp,agent_role,model,state) VALUES(?,?,?,?,?)",
                (task_id, ledger._utc_now().isoformat(), role, model, "running"),
            )
            db.commit()
        except sqlite3.IntegrityError as error:
            raise ReplayError(
                "Task ID already exists; inspect its status instead of replaying it."
            ) from error


def finish_task(task_id: str, state: str, reason: str = "") -> None:
    with ledger._connection() as db:
        db.execute(
            "UPDATE task_runs SET state=?,reason=? WHERE task_id=?",
            (state, reason, task_id),
        )
        db.commit()


def audit(task_id: str, event: str, **metadata) -> None:
    # Callers use fixed event/reason codes, never prompt/result/exception strings.
    allowed = {"step", "request_id", "tool", "success", "reason", "log_id"}
    if set(metadata) - allowed:
        raise ValueError("Unsupported audit metadata field.")
    with ledger._connection() as db:
        db.execute(
            "INSERT INTO audit_events(task_id,timestamp,event,metadata) VALUES(?,?,?,?)",
            (task_id, ledger._utc_now().isoformat(), event, json.dumps(metadata)),
        )
        db.commit()


def reserve(
    request_id: str,
    task_id: str,
    role: str,
    model: str,
    amount_usd: str,
    fingerprint: str,
) -> None:
    amount = ledger._money(amount_usd)
    with ledger._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute(
            "SELECT 1 FROM model_reservations WHERE request_id=?", (request_id,)
        ).fetchone():
            raise ReplayError(
                "Model request ID already exists; inspect/reconcile it before any retry."
            )
        summary = ledger._summary(db, ledger._utc_now())
        if summary["budget_exceeded"] or amount > Decimal(summary["available_usd"]):
            raise BudgetReservationError(
                "Insufficient unreserved daily budget; model request was not sent."
            )
        db.execute(
            "INSERT INTO model_reservations(request_id,task_id,timestamp,agent_role,model,amount_usd,fingerprint,state) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                request_id,
                task_id,
                ledger._utc_now().isoformat(),
                role,
                model,
                format(amount, "f"),
                fingerprint,
                "reserved",
            ),
        )
        db.commit()


def mark_sent(request_id: str) -> None:
    with ledger._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        result = db.execute(
            "UPDATE model_reservations SET state='inflight' WHERE request_id=? AND state='reserved'",
            (request_id,),
        )
        if result.rowcount != 1:
            raise ReplayError("Request is not an unsent reservation; do not resend it.")
        db.commit()


def mark_uncertain(request_id: str) -> None:
    with ledger._connection() as db:
        db.execute(
            "UPDATE model_reservations SET state='uncertain' WHERE request_id=? AND state='inflight'",
            (request_id,),
        )
        db.commit()


def settle(
    request_id: str, input_tokens: int, output_tokens: int, cost_usd: str
) -> dict:
    cost = ledger._money(cost_usd)
    if any(
        type(value) is not int or not 0 <= value <= 2**63 - 1
        for value in (input_tokens, output_tokens)
    ):
        raise ValueError("Usage token counts must be nonnegative integers.")
    with ledger._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT timestamp,agent_role,model,amount_usd,state,input_tokens,output_tokens,cost_usd,log_id "
            "FROM model_reservations WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if row is None or row[4] not in {"inflight", "uncertain", "settled"}:
            raise ValueError("Only sent/uncertain model requests can be settled.")
        if row[4] == "settled":
            if (row[5], row[6], Decimal(row[7])) != (input_tokens, output_tokens, cost):
                raise ValueError(
                    "Settlement does not match the already recorded usage."
                )
            log_id = row[8]
        else:
            cursor = db.execute(
                "INSERT INTO token_logs(timestamp,agent_role,model,input_tokens,output_tokens,cost_usd,request_id) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    row[0],
                    row[1],
                    row[2],
                    input_tokens,
                    output_tokens,
                    format(cost, "f"),
                    request_id,
                ),
            )
            log_id = cursor.lastrowid
            db.execute(
                "UPDATE model_reservations SET state='settled',input_tokens=?,output_tokens=?,cost_usd=?,log_id=? "
                "WHERE request_id=?",
                (input_tokens, output_tokens, format(cost, "f"), log_id, request_id),
            )
        summary = ledger._summary(db, ledger._utc_now())
        db.commit()
    return {"log_id": log_id, "reservation_exceeded": cost > Decimal(row[3]), **summary}


def release_confirmed_unbilled(request_id: str) -> None:
    """Operator-only recovery after confirming no provider charge; never automatic."""
    with ledger._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute(
            "UPDATE model_reservations SET state='released' "
            "WHERE request_id=? AND state IN ('reserved','inflight','uncertain')",
            (request_id,),
        )
        if changed.rowcount != 1:
            raise ValueError("Request is missing or already settled/released.")
        db.commit()


def claim_tool(task_id: str, call_id: str, name: str) -> None:
    with ledger._connection() as db:
        try:
            db.execute(
                "INSERT INTO tool_invocations VALUES(?,?,?,?)",
                (task_id, call_id, name, "started"),
            )
            db.commit()
        except sqlite3.IntegrityError as error:
            raise ReplayError(
                "Tool call ID already exists; side effects must not be replayed."
            ) from error


def finish_tool(task_id: str, call_id: str, success: bool) -> None:
    with ledger._connection() as db:
        db.execute(
            "UPDATE tool_invocations SET state=? WHERE task_id=? AND call_id=?",
            ("completed" if success else "failed", task_id, call_id),
        )
        db.commit()


def task_status(task_id: str) -> dict:
    """Read metadata for crash/restart recovery; never automatically rerun a task."""
    with ledger._connection() as db:
        row = db.execute(
            "SELECT timestamp,agent_role,model,state,reason FROM task_runs WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Unknown task ID.")
        pending = db.execute(
            "SELECT request_id,state,amount_usd FROM model_reservations WHERE task_id=?",
            (task_id,),
        ).fetchall()
        tools = db.execute(
            "SELECT call_id,tool_name,state FROM tool_invocations WHERE task_id=?",
            (task_id,),
        ).fetchall()
        events = db.execute(
            "SELECT event,metadata FROM audit_events WHERE task_id=? ORDER BY id",
            (task_id,),
        ).fetchall()
    return {
        "task_id": task_id,
        "timestamp": row[0],
        "role": row[1],
        "model": row[2],
        "state": row[3],
        "reason": row[4],
        "requests": [
            {"request_id": r[0], "state": r[1], "reserved_usd": r[2]} for r in pending
        ],
        "tools": [{"call_id": r[0], "tool": r[1], "state": r[2]} for r in tools],
        "events": [{"event": r[0], "metadata": json.loads(r[1])} for r in events],
    }
