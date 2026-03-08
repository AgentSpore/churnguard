from __future__ import annotations
from pydantic import BaseModel


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
