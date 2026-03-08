# ChurnGuard

> Cancel flow automation for SaaS. Intercept churn before it happens — trigger personalised save offers (pause, downgrade, discount) based on cancellation reason. Track save rate and MRR recovered.

## Problem

SaaS companies lose 5-10% of MRR monthly to churn. Most cancel flows are a single "Are you sure?" button. Without a structured save flow, companies have no visibility into why users leave and no automated way to retain them — leaving 20-40% of potentially saveable customers untouched.

## Market

- **TAM**: $14.7B — Customer retention and churn management software (2025)
- **SAM**: ~$2.1B — Cancel flow and retention tools for SaaS companies (~180K SaaS products)
- **CAGR**: 16.2% through 2030 (SaaS proliferation + LTV optimisation focus)
- **Trend**: Average SaaS save rate with structured cancel flows is 15-25% vs 2-5% without (ProfitWell, 2025)

## Competitors

| Tool | Strength | Weakness |
|------|----------|----------|
| Churnkey | Full cancel flow UI | $200+/mo, JS snippet only |
| Paddle Retain | Deep Paddle integration | Paddle-only |
| Brightback | Enterprise-grade | Expensive, long onboarding |
| Baremetrics | Analytics + cancellation insights | Stripe-only, no automation |
| Manual flows | Free | No tracking, no personalisation |

## Differentiation

- **API-first** — embed into any stack, any payment provider
- **Reason-based offer rules** — automatic offer selection (pause/downgrade/discount) by cancellation reason
- **MRR recovery tracking** — see exactly how much revenue was saved each month

## Economics

- **Pricing**: $49/mo (up to 100 cancel events), $149/mo (unlimited), $399/mo (white-label)
- **Target**: B2C/B2B SaaS with $10K+ MRR and self-serve cancellation
- **MRR at scale**: 1,500 customers × $149 = **$223K MRR / $2.7M ARR**
- **CAC**: ~$200 (dev community + content), LTV: $1,788 (12mo avg) → LTV/CAC = 8.9×

## Scoring

| Criterion | Score |
|-----------|-------|
| Pain severity | 4/5 |
| Market size | 4/5 |
| Technical barrier | 3/5 |
| Competitive gap | 3/5 |
| Monetisation clarity | 5/5 |
| **Total** | **3.8/5** |

## API Endpoints

```
POST /cancel                        — initiate cancel event, get personalised save offer
POST /cancel/{id}/outcome           — record saved or cancelled decision
GET  /events?outcome=               — list cancel events (filter: pending/saved/cancelled)
GET  /stats                         — save rate %, MRR saved, top cancellation reasons
```

## Run

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# Docs at http://localhost:8000/docs
```
