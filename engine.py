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

CREATE TABLE IF NOT EXISTS winback_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    reason_filter TEXT,
    plan_filter TEXT,
    offer_type TEXT NOT NULL,
    offer_detail TEXT NOT NULL,
    delay_days INTEGER NOT NULL DEFAULT 7,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS winback_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    cancel_event_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    plan TEXT NOT NULL,
    reason TEXT NOT NULL,
    mrr REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    sent_at TEXT,
    converted_at TEXT,
    FOREIGN KEY (campaign_id) REFERENCES winback_campaigns(id),
    FOREIGN KEY (cancel_event_id) REFERENCES cancel_events(id)
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


async def create_winback(db: aiosqlite.Connection, data: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    cur = await db.execute(
        """INSERT INTO winback_campaigns
           (name, reason_filter, plan_filter, offer_type, offer_detail, delay_days, status, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (data["name"], data.get("reason_filter"), data.get("plan_filter"),
         data["offer_type"], data["offer_detail"], data.get("delay_days", 7),
         "draft", now),
    )
    await db.commit()
    return await get_winback(db, cur.lastrowid)


async def get_winback(db: aiosqlite.Connection, campaign_id: int) -> dict | None:
    rows = await db.execute_fetchall(
        "SELECT * FROM winback_campaigns WHERE id=?", (campaign_id,)
    )
    if not rows:
        return None
    c = _row(rows[0])

    # Aggregate winback_events stats
    stats = await db.execute_fetchall("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status IN ('sent','converted','ignored') THEN 1 ELSE 0 END) AS sent,
            SUM(CASE WHEN status='converted' THEN 1 ELSE 0 END) AS converted,
            ROUND(SUM(CASE WHEN status='converted' THEN COALESCE(mrr,0) ELSE 0 END), 2) AS mrr_recovered
        FROM winback_events WHERE campaign_id=?
    """, (campaign_id,))
    s = stats[0] if stats else None
    total = s["total"] or 0 if s else 0
    sent = s["sent"] or 0 if s else 0
    converted = s["converted"] or 0 if s else 0
    mrr_recovered = s["mrr_recovered"] or 0.0 if s else 0.0

    return {
        "id": c["id"],
        "name": c["name"],
        "reason_filter": c["reason_filter"],
        "plan_filter": c["plan_filter"],
        "offer_type": c["offer_type"],
        "offer_detail": c["offer_detail"],
        "delay_days": c["delay_days"],
        "status": c["status"],
        "eligible_count": total,
        "sent_count": sent,
        "converted_count": converted,
        "conversion_rate_pct": round(converted / sent * 100, 1) if sent else 0.0,
        "mrr_recovered": mrr_recovered,
        "created_at": c["created_at"],
    }


async def list_winbacks(db: aiosqlite.Connection) -> list[dict]:
    rows = await db.execute_fetchall(
        "SELECT id FROM winback_campaigns ORDER BY id DESC"
    )
    result = []
    for r in rows:
        wb = await get_winback(db, r["id"])
        if wb:
            result.append(wb)
    return result


async def send_winback(db: aiosqlite.Connection, campaign_id: int) -> dict:
    """Find eligible cancelled users and create winback_events for them."""
    campaign = await db.execute_fetchall(
        "SELECT * FROM winback_campaigns WHERE id=?", (campaign_id,)
    )
    if not campaign:
        raise ValueError("Campaign not found")
    c = _row(campaign[0])
    if c["status"] == "sent":
        raise ValueError("Campaign already sent")

    # Build query for eligible cancelled users
    conditions = ["outcome = 'cancelled'"]
    params = []

    if c["reason_filter"]:
        conditions.append("reason = ?")
        params.append(c["reason_filter"])
    if c["plan_filter"]:
        conditions.append("plan = ?")
        params.append(c["plan_filter"])

    # delay_days filter: only users cancelled at least N days ago
    conditions.append(
        "julianday('now') - julianday(updated_at) >= ?"
    )
    params.append(c["delay_days"])

    where = " AND ".join(conditions)
    rows = await db.execute_fetchall(
        f"SELECT * FROM cancel_events WHERE {where} ORDER BY updated_at DESC",
        tuple(params),
    )

    # Exclude users already targeted by this campaign
    existing = await db.execute_fetchall(
        "SELECT cancel_event_id FROM winback_events WHERE campaign_id=?", (campaign_id,)
    )
    existing_ids = {r["cancel_event_id"] for r in existing}

    now = datetime.now(timezone.utc).isoformat()
    new_count = 0
    for r in rows:
        if r["id"] in existing_ids:
            continue
        await db.execute(
            """INSERT INTO winback_events
               (campaign_id, cancel_event_id, user_id, plan, reason, mrr, status, sent_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (campaign_id, r["id"], r["user_id"], r["plan"], r["reason"], r["mrr"], "sent", now),
        )
        new_count += 1

    await db.execute(
        "UPDATE winback_campaigns SET status='sent' WHERE id=?", (campaign_id,)
    )
    await db.commit()

    return await get_winback(db, campaign_id)


async def convert_winback_event(db: aiosqlite.Connection, campaign_id: int, event_id: int) -> dict | None:
    """Mark a winback event as converted (user came back)."""
    now = datetime.now(timezone.utc).isoformat()
    cur = await db.execute(
        "UPDATE winback_events SET status='converted', converted_at=? WHERE id=? AND campaign_id=?",
        (now, event_id, campaign_id),
    )
    await db.commit()
    if cur.rowcount == 0:
        return None
    rows = await db.execute_fetchall(
        "SELECT * FROM winback_events WHERE id=?", (event_id,)
    )
    return _row(rows[0]) if rows else None


async def list_winback_events(db: aiosqlite.Connection, campaign_id: int) -> list[dict]:
    rows = await db.execute_fetchall(
        "SELECT * FROM winback_events WHERE campaign_id=? ORDER BY id DESC", (campaign_id,)
    )
    return [_row(r) for r in rows]
