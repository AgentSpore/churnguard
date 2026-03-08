from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from models import CancelRequest, CancelResponse, OutcomeUpdate
from engine import init_db, create_cancel_event, update_outcome, list_events, get_stats

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
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/cancel")
async def initiate_cancel(body: CancelRequest):
    """
    Call when a user initiates cancellation.
    Returns the cancel event + a personalised save offer based on their reason.
    Embed this in your cancel flow UI.
    """
    event, offer = await create_cancel_event(app.state.db, body.model_dump())
    return {"event": event, "offer": offer}


@app.post("/cancel/{event_id}/outcome", response_model=CancelResponse)
async def record_outcome(event_id: int, body: OutcomeUpdate):
    """
    Record whether the user was saved or cancelled after seeing the offer.
    Call this when the user makes their final decision.
    """
    if body.outcome not in ("saved", "cancelled"):
        raise HTTPException(422, "outcome must be 'saved' or 'cancelled'")
    event = await update_outcome(app.state.db, event_id, body.outcome, body.offer_accepted)
    if not event:
        raise HTTPException(404, "Cancel event not found")
    return event


@app.get("/events", response_model=list[CancelResponse])
async def list_cancel_events(
    outcome: str | None = Query(None, description="Filter: pending, saved, cancelled"),
):
    """List cancel events for your dashboard."""
    return await list_events(app.state.db, outcome)


@app.get("/stats")
async def churn_stats():
    """
    Aggregate stats: total cancel attempts, save rate (%),
    MRR saved, top cancellation reasons.
    """
    return await get_stats(app.state.db)
