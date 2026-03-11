from __future__ import annotations
from pydantic import BaseModel, Field


class CancelRequest(BaseModel):
    user_id: str
    plan: str
    reason: str  # too_expensive | missing_feature | not_using | competitor | other
    mrr: float | None = None
    notes: str | None = None


class CancelResponse(BaseModel):
    id: int
    user_id: str
    plan: str
    reason: str
    mrr: float | None
    notes: str | None
    offer_shown: str | None   # pause | downgrade | discount | none
    outcome: str              # saved | cancelled | pending
    created_at: str
    updated_at: str


class OutcomeUpdate(BaseModel):
    outcome: str   # saved | cancelled
    offer_accepted: str | None = None


class SaveOffer(BaseModel):
    offer_type: str   # pause | downgrade | discount
    detail: str


class WinbackCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    reason_filter: str | None = Field(None, description="Only target users who cancelled for this reason")
    plan_filter: str | None = Field(None, description="Only target users on this plan")
    offer_type: str = Field(..., description="pause | downgrade | discount | custom")
    offer_detail: str = Field(..., min_length=1, description="Message/offer shown to churned user")
    delay_days: int = Field(7, ge=1, le=90, description="Days after cancellation before sending winback")


class WinbackEventResponse(BaseModel):
    id: int
    campaign_id: int
    cancel_event_id: int
    user_id: str
    plan: str
    reason: str
    mrr: float | None
    status: str  # pending | sent | converted | ignored
    sent_at: str | None
    converted_at: str | None


class WinbackResponse(BaseModel):
    id: int
    name: str
    reason_filter: str | None
    plan_filter: str | None
    offer_type: str
    offer_detail: str
    delay_days: int
    status: str  # draft | sent | completed
    eligible_count: int
    sent_count: int
    converted_count: int
    conversion_rate_pct: float
    mrr_recovered: float
    created_at: str
