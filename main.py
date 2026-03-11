from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from models import (
    CancelRequest, CancelResponse, OutcomeUpdate,
    WinbackCreate, WinbackResponse, WinbackEventResponse,
)
from engine import (
    init_db, create_cancel_event, get_event,
    update_outcome, list_events, export_events_csv, get_stats,
    get_stats_by_offer, get_stats_by_plan,
    create_winback, list_winbacks, get_winback, send_winback,
    convert_winback_event, list_winback_events,
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
        "Win back churned users with targeted re-engagement campaigns. "
        "Track save rate, win-back conversion, and MRR recovered."
    ),
    version="0.4.0",
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
    """Per-offer effectiveness: save rate and MRR recovered for each offer type."""
    return await get_stats_by_offer(app.state.db)


@app.get("/stats/by-plan")
async def stats_by_plan():
    """Per-plan breakdown: cancel attempts, save rate, MRR at risk and recovered."""
    return await get_stats_by_plan(app.state.db)


@app.post("/winback", response_model=WinbackResponse, status_code=201)
async def create_winback_campaign(body: WinbackCreate):
    """Create a win-back campaign targeting churned users by reason/plan with a custom offer."""
    return await create_winback(app.state.db, body.model_dump())


@app.get("/winback", response_model=list[WinbackResponse])
async def list_winback_campaigns():
    """List all win-back campaigns with conversion stats."""
    return await list_winbacks(app.state.db)


@app.get("/winback/{campaign_id}", response_model=WinbackResponse)
async def winback_detail(campaign_id: int):
    """Win-back campaign detail with eligible count, sent, converted, MRR recovered."""
    wb = await get_winback(app.state.db, campaign_id)
    if not wb:
        raise HTTPException(404, "Win-back campaign not found")
    return wb


@app.get("/winback/{campaign_id}/events", response_model=list[WinbackEventResponse])
async def winback_events(campaign_id: int):
    """List all winback events (users targeted) for a campaign."""
    wb = await get_winback(app.state.db, campaign_id)
    if not wb:
        raise HTTPException(404, "Win-back campaign not found")
    return await list_winback_events(app.state.db, campaign_id)


@app.post("/winback/{campaign_id}/send", response_model=WinbackResponse)
async def send_winback_campaign(campaign_id: int):
    """Send win-back offers to eligible churned users (cancelled + delay_days elapsed)."""
    try:
        return await send_winback(app.state.db, campaign_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/winback/{campaign_id}/convert/{event_id}", response_model=WinbackEventResponse)
async def mark_converted(campaign_id: int, event_id: int):
    """Mark a churned user as converted (won back). Updates conversion stats."""
    result = await convert_winback_event(app.state.db, campaign_id, event_id)
    if not result:
        raise HTTPException(404, "Winback event not found")
    return result
