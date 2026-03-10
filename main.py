from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from models import CancelRequest, CancelResponse, OutcomeUpdate
from engine import (
    init_db, create_cancel_event, get_event,
    update_outcome, list_events, export_events_csv, get_stats,
    get_stats_by_offer, get_stats_by_plan,
)

DB_PATH = "churnguard.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await init_db(DB_PATH)
    yield
    await app.state.db.close()


app = FastAPI(
    title="ChurnGuard",
    description=(
        "Cancel flow automation for SaaS. "
        "Intercept churn before it happens — trigger personalised save offers "
        "(pause, downgrade, discount) based on cancellation reason. "
        "Track save rate and MRR recovered."
    ),
    version="0.3.0",
    lifespan=lifespan,
)


@app.post("/cancel")
async def initiate_cancel(body: CancelRequest):
    event, offer = await create_cancel_event(app.state.db, body.model_dump())
    return {"event": event, "offer": offer}


@app.post("/cancel/{event_id}/outcome", response_model=CancelResponse)
async def record_outcome(event_id: int, body: OutcomeUpdate):
    if body.outcome not in ("saved", "cancelled"):
        raise HTTPException(422, "outcome must be 'saved' or 'cancelled'")
    event = await update_outcome(app.state.db, event_id, body.outcome, body.offer_accepted)
    if not event:
        raise HTTPException(404, "Cancel event not found")
    return event


@app.get("/events/export/csv")
async def export_csv(
    outcome: str | None = Query(None, description="Filter by outcome: pending, saved, cancelled"),
):
    csv_data = await export_events_csv(app.state.db, outcome)
    filename = f"churnguard_events{'_' + outcome if outcome else ''}.csv"
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/events", response_model=list[CancelResponse])
async def list_cancel_events(
    outcome: str | None = Query(None, description="Filter: pending, saved, cancelled"),
):
    return await list_events(app.state.db, outcome)


@app.get("/events/{event_id}", response_model=CancelResponse)
async def cancel_event_detail(event_id: int):
    event = await get_event(app.state.db, event_id)
    if not event:
        raise HTTPException(404, "Cancel event not found")
    return event


@app.get("/stats")
async def churn_stats():
    """Overall: total attempts, save rate, MRR saved, top cancellation reasons."""
    return await get_stats(app.state.db)


@app.get("/stats/by-offer")
async def stats_by_offer():
    """Per-offer effectiveness: save rate and MRR recovered for each offer type (pause, downgrade, discount)."""
    return await get_stats_by_offer(app.state.db)


@app.get("/stats/by-plan")
async def stats_by_plan():
    """Per-plan breakdown: cancel attempts, save rate, MRR at risk and recovered per subscription tier."""
    return await get_stats_by_plan(app.state.db)
