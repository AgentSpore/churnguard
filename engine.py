from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import aiosqlite

SQL_TABLES = """
CREATE TABLE IF NOT EXISTS cancel_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    plan TEXT NOT NULL,
    reason TEXT NOT NULL,
    mrr REAL,
    notes TEXT,
    offer_shown TEXT,
    outcome TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

OFFER_RULES: dict[str, str] = {
    "too_expensive": "downgrade",
    "not_using": "pause",
    "missing_feature": "none",
    "competitor": "discount",
    "other": "none",
}

OFFER_DETAILS: dict[str, str] = {
    "downgrade": "Switch to our Starter plan at 50% off — keep core features.",
    "pause": "Pause your account for up to 3 months. Resume anytime, no data lost.",
    "discount": "Stay 3 more months at 30% off — no strings attached.",
    "none": "We're sorry to see you go. Your data will be kept for 30 days.",
}


async def init_db(path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.executescript(SQL_TABLES)
    await db.commit()
    return db


def _row(r: aiosqlite.Row) -> dict:
    return {k: r[k] for k in r.keys()}


def _offer_for_reason(reason: str) -> tuple[str, str]:
    offer_type = OFFER_RULES.get(reason, "none")
    detail = OFFER_DETAILS.get(offer_type, OFFER_DETAILS["none"])
    return offer_type, detail


async def create_cancel_event(db: aiosqlite.Connection, data: dict) -> tuple[dict, dict]:
    now = datetime.now(timezone.utc).isoformat()
    offer_type, offer_detail = _offer_for_reason(data["reason"])
    cur = await db.execute(
        """INSERT INTO cancel_events
           (user_id, plan, reason, mrr, notes, offer_shown, outcome, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (data["user_id"], data["plan"], data["reason"],
         data.get("mrr"), data.get("notes"),
         offer_type if offer_type != "none" else None,
         "pending", now, now),
    )
    await db.commit()
    rows = await db.execute_fetchall("SELECT * FROM cancel_events WHERE id = ?", (cur.lastrowid,))
    event = _row(rows[0])
    offer = {"offer_type": offer_type, "detail": offer_detail}
    return event, offer


async def get_event(db: aiosqlite.Connection, event_id: int) -> dict | None:
    rows = await db.execute_fetchall(
        "SELECT * FROM cancel_events WHERE id = ?", (event_id,)
    )
    return _row(rows[0]) if rows else None


async def update_outcome(db: aiosqlite.Connection, event_id: int, outcome: str, offer_accepted: str | None) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    cur = await db.execute(
        "UPDATE cancel_events SET outcome=?, offer_shown=COALESCE(?,offer_shown), updated_at=? WHERE id=?",
        (outcome, offer_accepted, now, event_id),
    )
    await db.commit()
    if cur.rowcount == 0:
        return None
    rows = await db.execute_fetchall("SELECT * FROM cancel_events WHERE id = ?", (event_id,))
    return _row(rows[0])


async def list_events(db: aiosqlite.Connection, outcome: str | None = None) -> list[dict]:
    if outcome:
        rows = await db.execute_fetchall(
            "SELECT * FROM cancel_events WHERE outcome=? ORDER BY created_at DESC LIMIT 200", (outcome,)
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM cancel_events ORDER BY created_at DESC LIMIT 200"
        )
    return [_row(r) for r in rows]


async def export_events_csv(db: aiosqlite.Connection, outcome: str | None = None) -> str:
    if outcome:
        rows = await db.execute_fetchall(
            "SELECT * FROM cancel_events WHERE outcome=? ORDER BY created_at DESC", (outcome,)
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM cancel_events ORDER BY created_at DESC"
        )
    buf = io.StringIO()
    fields = ["id", "user_id", "plan", "reason", "mrr", "notes",
              "offer_shown", "outcome", "created_at", "updated_at"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r[k] for k in fields})
    return buf.getvalue()


async def get_stats(db: aiosqlite.Connection) -> dict:
    rows = await db.execute_fetchall(
        "SELECT outcome, COUNT(*) as cnt, SUM(COALESCE(mrr,0)) as mrr FROM cancel_events GROUP BY outcome"
    )
    by_outcome = {r["outcome"]: {"count": r["cnt"], "mrr": round(r["mrr"], 2)} for r in rows}
    total = sum(v["count"] for v in by_outcome.values())
    saved = by_outcome.get("saved", {}).get("count", 0)
    save_rate = round(saved / total * 100, 1) if total else 0.0
    mrr_saved = by_outcome.get("saved", {}).get("mrr", 0.0)

    reason_rows = await db.execute_fetchall(
        "SELECT reason, COUNT(*) as cnt FROM cancel_events GROUP BY reason ORDER BY cnt DESC"
    )
    top_reasons = [{"reason": r["reason"], "count": r["cnt"]} for r in reason_rows]

    return {
        "total_cancel_attempts": total,
        "saved": saved,
        "save_rate_pct": save_rate,
        "mrr_saved": mrr_saved,
        "by_outcome": by_outcome,
        "top_reasons": top_reasons,
    }


async def get_stats_by_offer(db: aiosqlite.Connection) -> list[dict]:
    """Per-offer effectiveness: how many users saw each offer, save rate, MRR recovered."""
    rows = await db.execute_fetchall("""
        SELECT
            COALESCE(offer_shown, 'none') AS offer_type,
            COUNT(*) AS shown,
            SUM(CASE WHEN outcome='saved' THEN 1 ELSE 0 END) AS saved,
            ROUND(SUM(CASE WHEN outcome='saved' THEN COALESCE(mrr,0) ELSE 0 END), 2) AS mrr_saved
        FROM cancel_events
        WHERE outcome != 'pending'
        GROUP BY offer_type
        ORDER BY saved DESC
    """)
    result = []
    for r in rows:
        shown = r["shown"] or 0
        saved = r["saved"] or 0
        result.append({
            "offer_type": r["offer_type"],
            "shown": shown,
            "saved": saved,
            "declined": shown - saved,
            "save_rate_pct": round(saved / shown * 100, 1) if shown else 0.0,
            "mrr_saved": r["mrr_saved"] or 0.0,
        })
    return result


async def get_stats_by_plan(db: aiosqlite.Connection) -> list[dict]:
    """Per-plan breakdown: cancel attempts, save rate, MRR at risk and recovered."""
    rows = await db.execute_fetchall("""
        SELECT
            plan,
            COUNT(*) AS attempts,
            SUM(CASE WHEN outcome='saved' THEN 1 ELSE 0 END) AS saved,
            ROUND(SUM(COALESCE(mrr,0)), 2) AS mrr_at_risk,
            ROUND(SUM(CASE WHEN outcome='saved' THEN COALESCE(mrr,0) ELSE 0 END), 2) AS mrr_saved
        FROM cancel_events
        GROUP BY plan
        ORDER BY attempts DESC
    """)
    result = []
    for r in rows:
        attempts = r["attempts"] or 0
        saved = r["saved"] or 0
        result.append({
            "plan": r["plan"],
            "cancel_attempts": attempts,
            "saved": saved,
            "save_rate_pct": round(saved / attempts * 100, 1) if attempts else 0.0,
            "mrr_at_risk": r["mrr_at_risk"] or 0.0,
            "mrr_saved": r["mrr_saved"] or 0.0,
        })
    return result
