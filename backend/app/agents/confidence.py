"""
Recommendation confidence scoring -- LLM-free, so both the multi-agent
workflow (app/agents/workflow.py) and the batch pipeline (app/pipeline.py)
can import it without pulling in the IndiaAI SDK integration stack (same rule as
app/agents/pitch.py).

Confidence answers "how sure are we this recommendation is RIGHT for this
customer" -- deliberately NOT the same thing as revenue_score / deal size.
It blends three inputs and then applies honest penalties:

  * llm_confidence   -- the Recommendation agent's own self-assessment
  * data_completeness -- how much of the evidence we'd want was actually
                         present for this customer (thin data -> lower conf)
  * retrieval_fit    -- how well the picked product fits the customer's
                         current plan/tier (a clean one-tier upgrade fits
                         better than a lateral or a big leap)

revenue_score is intentionally NOT an input -- a huge-upside product we're
only guessing at should read as high potential but LOW confidence.
"""

from app import db
from app.agents.payload import is_schema_free_tenant
from app.agents.pitch import catalog_lookup, tier_of
from app.prefilter import compute_usage_trend  # noqa: F401  (kept for parity/testing)


def clamp01(x: float) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, x))


def compute_data_completeness(
    customer: dict,
    usage_rows: list[dict],
    tickets: list[dict],
    signal_request: dict | None = None,
    tenant_id: str = "default",
) -> float:
    """Fraction (0-1) of the core upsell signals actually present & non-null
    for this customer. Missing data -> lower confidence, never an exception.

    Six equally-weighted checks, plus a small bonus when the tenant has any
    discovered dynamic fields for this customer (extra evidence the agents
    can reason over that a bare fixed-schema tenant wouldn't have)."""
    checks = []

    # Usage trend is only meaningful with >=2 months of real scores -- a
    # single row or all-null scores makes compute_usage_trend a 0-by-default,
    # which we must not count as "signal present".
    scored = [u for u in (usage_rows or []) if u.get("feature_usage_score") is not None]
    checks.append(len(scored) >= 2)

    # Current adoption level: latest usage row has a real feature score.
    checks.append(bool(usage_rows) and usage_rows[-1].get("feature_usage_score") is not None)

    # Any support-ticket history at all.
    checks.append(len(tickets or []) >= 1)

    # Renewal genuinely known. Schema-free synthetic customers get a
    # today+365 default (db.get_customers) which must NOT count as real; for
    # those tenants, require the concept to actually resolve to a column.
    if is_schema_free_tenant(tenant_id):
        try:
            checks.append(db.resolve_concept(tenant_id, "renewal_date") is not None)
        except Exception:
            checks.append(False)
    else:
        checks.append(customer.get("renewal_date") is not None)

    # Seat count (drives deal value); 0/None is the synthetic default.
    checks.append(customer.get("seats") not in (None, 0))

    # A real current plan/tier to anchor upgrade paths against.
    checks.append(customer.get("plan_tier") not in (None, "", "Unknown"))

    completeness = sum(1 for c in checks if c) / len(checks)

    # Bonus for tenant-specific discovered evidence (customer/ticket/usage).
    if signal_request:
        if (
            signal_request.get("dynamic_fields")
            or signal_request.get("ticket_dynamic_fields")
            or signal_request.get("usage_dynamic_fields")
            or signal_request.get("datasets")
        ):
            completeness = min(1.0, completeness + 0.05)

    return round(completeness, 3)


def compute_retrieval_fit(
    catalog: list[dict],
    current_product: str | None,
    recommended_product: str | None,
    retrieval_method: str | None = None,
    vector_score: float | None = None,
) -> float:
    """How well the recommended product fits the customer's current plan,
    from the tenant's own catalog tiers. A clean one-tier-up upgrade fits
    best; same-tier cross-sell is fine; a big leap or a downgrade fits less.

    Works with NO embeddings (the default -- use_vector_search is off for
    most tenants): fit is derived from tier adjacency alone. If a real
    cosine `vector_score` (0-1) is available it's blended in 50/50."""
    if not recommended_product:
        return 0.0

    current = catalog_lookup(catalog, current_product)
    rec = catalog_lookup(catalog, recommended_product)
    ct = tier_of(current) if current else None
    rt = tier_of(rec) if rec else None

    fit = 0.5  # neutral default when we can't reason about tiers at all
    if ct is not None and rt is not None:
        delta = rt - ct
        if delta == 1:
            fit = 0.9   # ideal: the very next tier up
        elif delta == 0:
            fit = 0.7   # lateral cross-sell
        elif delta >= 2:
            fit = 0.6   # a bigger leap -- plausible but less obviously right
        else:
            fit = 0.4   # a downgrade suggestion is a weak "fit"
    elif rt is not None:
        fit = 0.55      # rec has a tier, current plan unknown

    if vector_score is not None:
        fit = 0.5 * fit + 0.5 * clamp01(vector_score)

    return clamp01(fit)


def compute_confidence(
    *,
    llm_confidence: float | None,
    data_completeness: float,
    retrieval_fit: float,
    used_fallbacks: list[str] | None = None,
    is_low_confidence_pitch: bool = False,
    has_product: bool = True,
    critic_penalty: float | None = None,
) -> float:
    """Final 0-1 confidence. See module docstring for the philosophy.

    Ordering matters:
      * no product at all            -> 0.0 (nothing to be confident about)
      * low-confidence catalog pitch -> capped <= 0.25 (a starting point,
        never a data-backed match) -- this branch also absorbs critic-veto,
        high-churn-gate, and signal-rejected outcomes, since workflow.py
        fills a pitch after each of those.
    """
    used_fallbacks = used_fallbacks or []

    if not has_product:
        return 0.0
    if is_low_confidence_pitch:
        return round(min(0.25, 0.15 + 0.10 * clamp01(data_completeness)), 2)

    c_llm = 0.5 if llm_confidence is None else clamp01(llm_confidence)
    base = 0.50 * c_llm + 0.30 * clamp01(data_completeness) + 0.20 * clamp01(retrieval_fit)

    # The critic's independent moderation (approved-but-shaky).
    if critic_penalty:
        base *= (1 - clamp01(critic_penalty))

    # Heuristic fallbacks mean a step didn't get a real model read -- weight
    # the recommendation step hardest, the checks (critic/signal) less.
    if "recommendation" in used_fallbacks:
        base *= 0.60
    if "critic" in used_fallbacks:
        base *= 0.85
    if "signal" in used_fallbacks:
        base *= 0.90

    return round(max(0.05, min(0.95, base)), 2)
