# Product Requirements — Upsell Recommendation Agent

## Problem
Account Managers and CSMs need a churn-aware view of which customers to upsell,
cross-sell, or retain — with clear justification and revenue value — instead of
blanket upsell campaigns that risk pushing at-risk customers out the door.

## Solution
A 5-agent sequential pipeline that scores churn risk per customer and generates
segment-appropriate recommendations:

- **HIGH churn** → retention offers, discounts, CSM escalation (never upsell)
- **MEDIUM churn** → feature adoption nudges + light cross-sell
- **LOW churn** → premium upgrades, complementary products, personalized upsell

## Users
- Account Managers — see per-customer recommendations + justification
- Customer Success Managers — catch high-churn accounts for escalation
- Sales Managers — track conversion (accepted vs rejected) across segments

## Data
Synthetic only (Faker-generated): 60+ companies across usage, support, billing
signals and a static product catalog. See
[churn_scoring_logic.md](churn_scoring_logic.md) for the scoring model.

## Acceptance criteria
- [x] Synthetic generator produces varied data across all churn segments
- [x] Churn scoring is transparent and rule-documented
- [x] HIGH-churn customers only receive retention offers, never pure upsell
- [x] MEDIUM and LOW segments produce differentiated recommendation types
- [x] Every recommendation has revenue opportunity + confidence + justification
- [x] Zero-cost rule-based fallback if the LLM/agent call fails
- [x] Full pipeline runs end-to-end via one API call, reflected in the frontend
- [x] Recommendations can be marked accepted/rejected in an analytics view
