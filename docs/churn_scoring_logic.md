# Churn Scoring — Current Implementation

Traject shows a **deterministic 0–100 churn score** for customer analytics and can also show a **risk label determined by the recommendation/Critic workflow**. The displayed score may be clamped into the selected risk band's numeric range to prevent a contradictory label and number.

**Implementation references:** `backend/app/web_api.py` (`_churn`, `_reconcile_churn_score`) and `backend/app/prefilter.py` (`estimate_churn_risk`, `passes_prefilter`).

## Customer analytics score

The `_churn` function uses four additive components:

| Signal | Formula / treatment | Maximum |
|---|---|---:|
| Declining usage | `clamp(-usage_trend_pct * 1.4, 0, 45)` | 45 |
| Unresolved support tickets | `min(open_ticket_count * 7 + (10 if open_billing_issue else 0), 30)` | 30 |
| Renewal proximity | 18 points within 30 days; 11 within 60; 6 within 90 | 18 |
| Low engagement | `clamp((40 - adoption_pct) * 0.5, 0, 20)` | 20 |

```text
score = min(100, usage + support + renewal + engagement)
LOW:      0–33
MEDIUM:  34–66
HIGH:    67–100
```

This is the **dashboard score**, not a claim that the LLM mathematically computed churn. When the model's risk label differs from the deterministic result, `_reconcile_churn_score` adjusts the displayed score into the model label's band. The underlying numeric factors are still calculated locally.

## Operational decision gates

- `passes_prefilter` shortlists accounts on relevant growth, storage utilization, recent qualifying tickets, or upcoming renewal; thresholds may be tenant-calibrated.
- `estimate_churn_risk` provides a separate deterministic risk assessment for no-model and rule-based paths.
- The agent workflow validates candidate products and applies hard gates: high churn, insufficient evidence, failed recommendation, or Critic veto **must not generate an approved upsell**.

For the complete business conditions, see `backend/app/agents/workflow.py`, `backend/app/trust.py`, and tests in `backend/tests/test_trust_gates.py`.
