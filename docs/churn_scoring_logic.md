# Churn Scoring Logic

The churn risk score is a **transparent, rule-based** computation — not an LLM
black box. Every factor is normalized to a `0–1` risk value, multiplied by a
documented weight, and summed into a `0–100` score.

Source of truth: [`backend/config.py`](../backend/config.py) (`CHURN_WEIGHTS`,
thresholds) and [`backend/agents/churn_scoring_agent.py`](../backend/agents/churn_scoring_agent.py).

## Factors and normalization

| Factor | Signal(s) | Risk = 1 (worst) when… | Weight |
|---|---|---|---|
| `usage` | `login_frequency_per_week` | ~0 logins/week (10+/wk is healthy) | 0.25 |
| `adoption` | `feature_adoption_pct` | 0% features adopted | 0.20 |
| `support` | `open_tickets`, `avg_resolution_time_days` | ≥12 open tickets / ≥10-day resolution | 0.20 |
| `sentiment` | `csat_score` (1–5), `nps_score` (−100..100) | CSAT 1 / NPS −100 | 0.20 |
| `recency` | `days_since_last_login` | ≥30 days since last login | 0.15 |

Weights sum to `1.0`.

### Formulas

```
usage_risk     = clamp(1 - login_frequency_per_week / 10)
adoption_risk  = clamp(1 - feature_adoption_pct / 100)
support_risk   = clamp(0.6 * (open_tickets / 12) + 0.4 * (avg_resolution_days / 10))
sentiment_risk = clamp(0.5 * (1 - (csat - 1)/4) + 0.5 * (1 - (nps + 100)/200))
recency_risk   = clamp(days_since_last_login / 30)

score = 100 * Σ (factor_risk * weight)
```

## Segments

| Segment | Score | Strategy |
|---|---|---|
| **HIGH** | ≥ 70 | Retention only — discounts, save offers, CSM escalation. **Never upsell.** |
| **MEDIUM** | 40–69 | Balanced — feature adoption nudges + light cross-sell. |
| **LOW** | < 40 | Upsell / cross-sell — plan upgrades, add-ons, complementary products. |

Thresholds live in `config.CHURN_HIGH_THRESHOLD` (70) and
`config.CHURN_MEDIUM_THRESHOLD` (40). The segment gates everything downstream:
the Catalog Retrieval Agent filters eligible items by segment, so a HIGH-risk
customer physically cannot be shown upgrade-only items.
