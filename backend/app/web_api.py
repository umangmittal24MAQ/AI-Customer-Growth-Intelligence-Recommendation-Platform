"""
Frontend-facing API adapter.

The React frontend (see frontend/src/api/client.js) was built against a
specific REST contract -- /api/customers, /api/customers/{id}/analysis,
/api/generate-recommendations, /api/analytics/summary, etc. -- with richer,
UI-shaped fields (churn_score 0-100, churn_segment HIGH/MEDIUM/LOW, mrr,
bandwidth_data, executive_summary, ...) that the core backend model doesn't
store directly.

Rather than change the frontend, this module maps the existing backend data
(customers / usage_metrics / support_tickets / product_catalog) and the
multi-agent reasoning pipeline into exactly the shapes the frontend reads.
Everything the frontend can't get from raw columns (churn score, capacity
"bandwidth", customer insights) is derived deterministically here so the
same customer always renders the same numbers across every screen.
"""

import json
import zlib
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Depends, Depends
from pydantic import BaseModel

from app import db
from app.logging_config import get_logger
from app.pipeline import generate_recommendations
from app.auth import get_current_tenant
from app.insights import build_customer_insights
from app.prefilter import (
    compute_usage_trend,
    storage_pct_used,
    days_to_renewal,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api")

REGIONS = ["North America", "EMEA", "APAC", "LATAM"]
IDEAL_LOGIN_FREQ = 14  # logins/week that counts as "fully engaged"

# The React frontend is built around a Starter/Pro/Enterprise plan vocabulary
# (catalog eligibility, seat capacities, upgrade paths). The backend's real
# plan names are catalog product names (e.g. "Business Standard", "E1", "E3"),
# so map them to that vocabulary by catalog tier level for anything the UI
# renders. Internal pricing/upsell math still uses the real plan name.
PLAN_DISPLAY = {1: "Starter", 2: "Pro", 3: "Enterprise"}


# ---------------------------------------------------------------------------
# Small deterministic helpers -- keep every screen showing the same numbers
# ---------------------------------------------------------------------------
def _stable_pick(key: str, options: list):
    """Deterministic choice from `options` based on a stable hash of `key`."""
    return options[zlib.crc32(key.encode()) % len(options)]


def _catalog_index(catalog: list[dict]) -> dict:
    return {p["product_name"]: p for p in catalog}


def _plan_price(plan_tier: str, cat_index: dict) -> float:
    prod = cat_index.get(plan_tier)
    return float(prod["price_per_seat"]) if prod else 12.0


def _current_tier_level(plan_tier: str, cat_index: dict) -> int:
    prod = cat_index.get(plan_tier)
    return int(prod["tier_level"]) if prod else 1


def _display_plan(plan_tier: str, cat_index: dict) -> str:
    """Map a real backend plan name to the frontend's Starter/Pro/Enterprise
    vocabulary by catalog tier level (falls back to the raw name)."""
    return PLAN_DISPLAY.get(_current_tier_level(plan_tier, cat_index), plan_tier)


def _mrr(customer: dict, cat_index: dict) -> float:
    seats = customer.get("seats") or 0
    return round(_plan_price(customer.get("plan_tier"), cat_index) * seats, 2)


def _next_upsell_product(plan_tier: str, catalog: list[dict], cat_index: dict) -> dict | None:
    """The cheapest product one tier above the customer's current plan
    (a "core-plan" upgrade if one exists, otherwise any higher tier)."""
    current_tier = _current_tier_level(plan_tier, cat_index)
    higher = [p for p in catalog if int(p["tier_level"]) > current_tier]
    if not higher:
        return None
    core = [p for p in higher if p.get("category") == "core-plan"]
    pool = core or higher
    return min(pool, key=lambda p: int(p["tier_level"]))


def _annual_opportunity(customer: dict, catalog: list[dict], cat_index: dict) -> int:
    """Deterministic annual expansion value (ARR) if this customer moved to
    the next plan tier. Same scale/formula as the pipeline's deal-value math
    (price_per_seat * seats * 12) so numbers agree before and after a run."""
    seats = customer.get("seats") or 0
    if not seats:
        return 0
    nxt = _next_upsell_product(customer.get("plan_tier"), catalog, cat_index)
    current_price = _plan_price(customer.get("plan_tier"), cat_index)
    if nxt:
        delta = max(float(nxt["price_per_seat"]) - current_price, 2.0)
    else:
        # Already top tier -- model a representative add-on expansion instead.
        delta = max(current_price * 0.25, 3.0)
    return int(round(delta * seats * 12))


def _adoption_pct(customer: dict, usage_rows: list[dict]) -> int:
    """Feature-adoption percent (0-100) from the latest usage row's
    feature_usage_score, normalizing whether it's stored on a 0-1 or 0-100
    scale."""
    if not usage_rows:
        return 0
    raw = usage_rows[-1].get("feature_usage_score") or 0
    pct = raw * 100 if raw <= 1 else raw
    return int(round(min(max(pct, 0), 100)))


def _churn(customer: dict, usage_rows: list[dict], tickets: list[dict], adoption: int):
    """Deterministic churn score (0-100), risk band, and factor breakdown."""
    trend = compute_usage_trend(usage_rows)
    renewal_days = days_to_renewal(customer["renewal_date"])

    usage_factor = int(round(min(max(-trend * 1.4, 0), 45)))
    unresolved = [t for t in tickets if not t.get("resolved")]
    billing_open = any(
        t.get("category") == "billing" and not t.get("resolved") for t in tickets
    )
    ticket_factor = int(min(len(unresolved) * 7 + (10 if billing_open else 0), 30))
    if renewal_days <= 30:
        renewal_factor = 18
    elif renewal_days <= 60:
        renewal_factor = 11
    elif renewal_days <= 90:
        renewal_factor = 6
    else:
        renewal_factor = 0
    engagement_factor = int(round(min(max((40 - adoption) * 0.5, 0), 20)))

    score = min(100, usage_factor + ticket_factor + renewal_factor + engagement_factor)
    if score >= 67:
        risk = "HIGH"
    elif score >= 34:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    factor_breakdown = {
        "Usage Trend": usage_factor,
        "Support Tickets": ticket_factor,
        "Renewal Proximity": renewal_factor,
        "Low Engagement": engagement_factor,
    }
    return score, risk, factor_breakdown, trend, renewal_days


_RISK_BANDS = {"HIGH": (67, 100), "MEDIUM": (34, 66), "LOW": (0, 33)}


def _reconcile_churn_score(score: int, risk: str) -> int:
    """The numeric churn_score (0-100) is computed locally by _churn()
    below; the risk LABEL shown next to it can come from the agent/critic
    verdict instead (see the note at its call site), which uses its own
    judgment and isn't derived from this score at all. Left alone, the two
    can disagree -- e.g. a "HIGH CHURN" badge next to a 52/100 score that
    _churn()'s own thresholds would call MEDIUM. Clamp the score into the
    band the *displayed* risk label implies so the number and badge never
    visually contradict each other; the factor breakdown underneath still
    shows the real, unclamped signal-by-signal math for anyone who wants it.
    """
    lo, hi = _RISK_BANDS.get(risk, (0, 100))
    if lo <= score <= hi:
        return score
    return min(hi, max(lo, score))


def _bandwidth(customer: dict, usage_rows: list[dict], adoption: int, trend: float) -> dict:
    """Capacity/"bandwidth" object shaped exactly like the frontend's
    computeBandwidth() output (dimensions.seats/adoption/frequency, trend,
    headroom, opportunityScore) -- ported to Python so it can be served
    directly by /customers/{id}/analysis.

    active_users is now an OPTIONAL concept (see schema_mapping.py) -- a
    tenant with no such concept gets None back from get_usage(), not a
    fabricated 0. That matters here: 0 active_users would silently render
    as "0 of N seats used" (implying total non-adoption), whereas "no
    active_users concept for this tenant" should fall back to treating
    seat utilization as fully driven by adoption/frequency instead of
    inventing a seats number that was never really tracked.
    """
    latest = usage_rows[-1] if usage_rows else {}
    seat_capacity = customer.get("seats") or 50
    active_raw = latest.get("active_users")
    has_active_users_concept = active_raw is not None
    active = int(active_raw or 0)
    seats_used = min(active, seat_capacity)
    seat_pct = (
        int(round(seats_used / seat_capacity * 100)) if has_active_users_concept and seat_capacity else None
    )

    login_freq = max(1, int(round((adoption / 100) * IDEAL_LOGIN_FREQ)))
    freq_pct = min(int(round(login_freq / IDEAL_LOGIN_FREQ * 100)), 100)

    if seat_pct is None:
        # No seats/active_users concept for this tenant's business -- don't
        # let a fabricated number quietly drag the overall score around.
        # Reweight entirely onto adoption + frequency instead.
        overall = int(round(adoption * 0.6 + freq_pct * 0.4))
    else:
        overall = int(round(seat_pct * 0.4 + adoption * 0.35 + freq_pct * 0.25))

    if trend >= 5:
        delta = int(round(min(overall * 0.15, 18)))
    elif trend <= -5:
        delta = -int(round(min(overall * 0.12, 15)))
    else:
        delta = int(round(adoption * 0.03))
    previous = max(0, min(100, overall - delta))
    direction = "up" if delta > 3 else "down" if delta < -3 else "flat"
    if direction == "up":
        trend_label = f"{previous}% \u2192 {overall}% (\u2191 past 3 mo)"
    elif direction == "down":
        trend_label = f"{previous}% \u2192 {overall}% (\u2193 past 3 mo)"
    else:
        trend_label = f"{previous}% \u2192 {overall}% (\u2192 flat)"

    time_to_capacity = None
    if direction == "up" and delta > 0 and overall < 100:
        months = max(1, int(round((100 - overall) / delta * 3)))
        time_to_capacity = (
            "Approaching capacity now"
            if months <= 1
            else f"~{months} months to capacity at current growth"
        )
    elif overall >= 90:
        time_to_capacity = "Near capacity \u2014 act now"
    elif direction == "down":
        time_to_capacity = "Declining \u2014 expansion not recommended yet"

    headroom_pct = max(0, 100 - overall) / 100
    mrr_ceiling = {1: 500, 2: 2000, 3: 8000}.get(
        _stable_pick(customer["customer_id"], [1, 2, 3]), 2000
    )
    headroom_dollars = int(round(mrr_ceiling * headroom_pct))
    headroom_label = (
        f"~${headroom_dollars:,}/mo remaining before plan limits"
        if headroom_dollars > 0
        else "At or beyond plan capacity"
    )

    opp_score = min(100, int(round(overall * 0.5 + adoption * 0.3 + freq_pct * 0.2)))

    def _color(pct, hi=80, mid=50):
        return "emerald" if pct >= hi else "blue" if pct >= mid else "amber"

    return {
        "overall": overall,
        "previous": previous,
        "direction": direction,
        "trendLabel": trend_label,
        "trendDataSimulated": True,
        "timeToCapacity": time_to_capacity,
        "headroomDollars": headroom_dollars,
        "headroomLabel": headroom_label,
        "opportunityScore": opp_score,
        "dimensions": {
            "seats": (
                {
                    "used": seats_used,
                    "capacity": seat_capacity,
                    "pct": seat_pct,
                    "label": f"{seats_used} of {seat_capacity} seats used",
                    "color": _color(seat_pct),
                }
                if seat_pct is not None
                else {
                    "used": None,
                    "capacity": None,
                    "pct": None,
                    "label": "Not tracked for this account",
                    "color": "gray",
                }
            ),
            "adoption": {
                "pct": adoption,
                "label": f"{adoption}% of entitled features active",
                "color": _color(adoption, 70, 40),
            },
            "frequency": {
                "pct": freq_pct,
                "label": f"{login_freq}/wk login rate",
                "color": _color(freq_pct, 70, 40),
            },
        },
    }


def _trace_from_agent_trace(at: dict | None) -> list[dict]:
    """Turn the pipeline's agent_trace dict into the ordered step list the
    frontend's Chain-of-Thought modal renders ({agent, mode, detail, basis})."""
    if not at:
        return []
    agents_run = at.get("agents_run", [])
    fallbacks = set(at.get("fallbacks_used", []))
    steps = []
    if "deterministic_screen" in agents_run or "prefilter" in agents_run:
        steps.append({"agent": "Account Screening", "mode": "rules",
            "detail": "Evaluated account evidence and churn safeguards without an AI request.",
            "basis": at.get("reason_code") or at.get("signal_reason") or "Passed basic eligibility screening."})
    if "eligible_catalog" in agents_run:
        steps.append({"agent": "Catalog Eligibility", "mode": "rules",
            "detail": f"Restricted product choices to {at.get('candidate_count', 0)} eligible catalog items.",
            "basis": "Only within-family upgrades or explicitly evidenced cross-sells are eligible."})
    evidence = at.get("evidence") or []
    if evidence:
        excerpt = "; ".join(f"{e.get('source')}.{e.get('field')}: {e.get('value')}" for e in evidence[:5])
        steps.append({"agent": "Source Evidence", "mode": "rules",
            "detail": f"Captured {len(evidence)} verifiable field/value excerpts from imported data.",
            "basis": excerpt})
    if "signal" in agents_run:
        urgency = at.get("signal_urgency")
        reason = at.get("signal_reason")
        if at.get("outcome") == "not_shortlisted":
            detail = "Screened this customer against usage, support tickets, and renewal timing -- did not clear the bar to proceed."
        elif urgency:
            detail = (
                f"Screened this customer against usage, support tickets, and renewal "
                f"timing -- cleared to proceed with {urgency} urgency."
            )
        else:
            detail = ("Screened whether this customer is worth reasoning about based on "
                       "usage, support tickets, and renewal timing.")
        steps.append({
            "agent": "Signal Agent",
            "mode": "rules" if "signal" in fallbacks else "llm",
            "detail": detail,
            "basis": reason or "Customer passed the signal screen.",
        })
    if "recommendation" in agents_run:
        method = at.get("retrieval_method", "n/a")
        method_label = {
            "vector": "similarity search across the full catalog",
            "full_catalog_fallback": "a full review of the catalog",
            "skipped_small_catalog": "a direct review of the catalog (small enough to skip narrowing)",
        }.get(method, "a review of the catalog")
        candidates = at.get("candidate_products") or []
        product = at.get("recommended_product")
        candidate_note = (
            f" Candidates considered: {', '.join(candidates)}."
            if candidates else ""
        )
        steps.append({
            "agent": "Recommendation Agent",
            "mode": "rules" if "recommendation" in fallbacks else "llm",
            "detail": f"Selected the best-fit product from {len(candidates) or 'the'} "
                      f"candidate product(s), using {method_label}."
                      f"{candidate_note}",
            "basis": at.get("recommendation_rationale")
            or (f"Recommended {product}." if product else "No product clearly justified by the data."),
        })
    if "critic" in agents_run:
        churn_risk = at.get("churn_risk")
        approved = at.get("critic_approved")
        veto_reason = at.get("critic_veto_reason")
        churn_reason = at.get("critic_churn_risk_reason")
        basis_parts = []
        if churn_reason:
            basis_parts.append(f"Churn risk ({churn_risk or 'n/a'}): {churn_reason}")
        if veto_reason:
            basis_parts.append(f"{'Approved' if approved else 'Vetoed'}: {veto_reason}")
        basis = " | ".join(basis_parts) or (
            "Approved the recommendation." if approved else "Reviewed the recommendation."
        )
        steps.append({
            "agent": "Critic Agent",
            "mode": "rules" if "critic" in fallbacks else "llm",
            "detail": "Independent second opinion on churn risk and whether the "
                      "recommendation should stand.",
            "basis": basis,
        })
    deal_value = at.get("estimated_deal_value")
    if at.get("decision_status") not in ("qualified", None):
        return steps
    steps.append({
        "agent": "Deal Value",
        "mode": "rules",
        "detail": "Computed estimated annual deal value from catalog pricing and seat count.",
        "basis": at.get("deal_value_anomaly_reason")
        or (f"Estimated annual value: ${deal_value:,.2f}." if deal_value is not None else "Standard deal-value calculation."),
    })
    return steps


def _parse_agent_trace(raw) -> dict | None:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


def _data_gaps(counts: dict) -> list[str]:
    """Human-readable list of tenant-wide datasets that were never uploaded
    at all -- distinct from a customer legitimately having zero tickets or
    a flat usage history. Surfaced everywhere analysis results are shown so
    the UI can say "I don't have this data" instead of quietly computing
    numbers off an empty table."""
    gaps = []
    if counts.get("product_catalog", 0) == 0:
        if counts.get("product_catalog_demo_seed", 0) > 0:
            gaps.append("This tenant has no product catalog of its own — currently falling back to the shared demo catalog. Please provide this tenant's product catalog as well.")
        else:
            gaps.append("No product catalog uploaded — revenue opportunity and upsell recommendations can't be calculated. Please provide a product catalog for this tenant.")
    if counts.get("usage_metrics", 0) == 0:
        gaps.append("No usage metrics uploaded — churn/adoption analysis will rely on renewal date and support tickets only.")
    if counts.get("support_tickets", 0) == 0:
        gaps.append("No support ticket data uploaded — churn analysis won't reflect support signals.")
    return gaps


_RETENTION_ACTIONS = {
    "high_churn_gate": "High churn risk — hold new upsell offers and route to a retention/renewal conversation first.",
    "critic_vetoed": "Recommendation didn't hold up to review — revisit manually before proposing new spend.",
    "no_opportunity_found": "No upsell opportunity found this cycle — check back in after usage or plan changes.",
    "signal_rejected": "Didn't meet the bar for review this run — no action needed unless signals change.",
    "not_shortlisted": "Low-confidence suggestion only — not shortlisted this cycle; treat as a starting point, not a strong match.",
}

# Short, static "why" for each no_recommendation_reason_code -- shown ahead
# of the (separate) "what to do instead" text so the account manager sees
# the reason first. Kept distinct from _RETENTION_ACTIONS above because
# that map's text can be overridden per-customer by the Retention agent's
# own action_text (see _retention_action), but the underlying reason a
# customer wasn't shortlisted doesn't change with that override.
_NO_REC_REASONS = {
    "high_churn_gate": "High churn risk — upsell offers are paused until retention risk is addressed.",
    "critic_vetoed": "A candidate product was suggested but didn't hold up under the pipeline's own review.",
    "no_opportunity_found": "No upsell opportunity in the current catalog fit this customer's profile.",
    "signal_rejected": "Didn't meet the bar to be worth a full recommendation pass this cycle.",
    "not_shortlisted": "Only a low-confidence match was found, so it wasn't shortlisted.",
}


def _no_recommendation_reason(reason_code: str | None, churn_reason: str | None) -> str | None:
    """The "why" a customer has no upsell recommendation, shown separately
    from (and before) _retention_action's "what to do instead" text.

    Prefers churn_reason as-is: for every reason_code, this is now the
    Retention agent's own per-customer reason_summary (see
    agents/workflow.py and pipeline.py's _fill_retention_actions, which
    overwrite churn_reason with it once the agent runs) -- never the old
    static, rule-engine-only text. Falls back to the static map only for
    rows where no agent ever ran at all (e.g. agent-framework unavailable,
    or a row logged before this agent existed)."""
    if not reason_code:
        return None
    if churn_reason:
        return churn_reason
    return _NO_REC_REASONS.get(reason_code, "No recommendation was generated this cycle.")


def _parse_retention_action(stored_retention_action) -> dict | None:
    """Normalizes the two shapes this value can arrive in:
    - a dict, when called with the freshly-computed in-memory rec straight
      out of workflow.run_customer (e.g. the /generate-recommendations
      response path), which was never round-tripped through the DB, or
    - a JSON string, once it's been persisted to and read back from
      recommendations_log.retention_action (db.log_recommendation stores it
      via json.dumps).
    Returns None if there's nothing there or it doesn't parse cleanly."""
    if not stored_retention_action:
        return None
    if isinstance(stored_retention_action, dict):
        return stored_retention_action
    try:
        return json.loads(stored_retention_action)
    except (json.JSONDecodeError, TypeError):
        return None


def _retention_action(reason_code: str | None, stored_retention_action=None) -> str | None:
    """Human-readable "what to do instead" for a customer the pipeline
    processed but had no product to recommend for -- keeps a high-churn
    account from reading as simply 'not analyzed' in the UI.

    Prefers the Retention agent's own generated action (a concrete, specific
    next step for this account -- schedule a 1:1, offer something
    complimentary, run a training session, etc.), which may arrive either as
    a dict (fresh, pre-persistence) or a JSON string (read back from
    recommendations_log.retention_action). Falls back to the static generic
    map only for rows logged before that agent existed, or if the stored
    value fails to parse."""
    if not reason_code:
        return None
    parsed = _parse_retention_action(stored_retention_action)
    if parsed:
        text = parsed.get("action_text")
        if text:
            return text
    return _RETENTION_ACTIONS.get(reason_code, "No upsell recommendation this cycle — review manually.")


def _retention_action_detail(reason_code: str | None, stored_retention_action) -> dict | None:
    """Full structured retention action (action_type/action_text/talking_point)
    for callers that want more than the plain text, e.g. to show an icon per
    action_type in the UI. Returns None if nothing was ever generated."""
    if not reason_code:
        return None
    return _parse_retention_action(stored_retention_action)


def _stored_confidence(rec: dict | None) -> float | None:
    """The recommendation's real, persisted confidence (0-1). Falls back to
    the old revenue_score-derived estimate ONLY for legacy rows logged before
    the confidence column existed (confidence IS NULL) -- new rows always
    carry a genuine confidence from app/agents/confidence.py, so this is a
    transitional shim, not the primary source anymore."""
    if not rec:
        return None
    c = rec.get("confidence")
    if c is not None:
        return round(float(c), 2)
    return round(max(0.05, min(0.95, (rec.get("revenue_score") or 75) / 100)), 2)


# ---------------------------------------------------------------------------
# Per-customer summary used by the customers list + analytics rollups
# ---------------------------------------------------------------------------
def _customer_card(tenant_id: str, customer: dict, catalog: list[dict], cat_index: dict, latest_rec: dict | None, dataset_counts: dict = None) -> dict:
    """Per-customer summary card. `analyzed` is true only once the agent
    pipeline has actually produced a recommendations_log row for this
    customer -- churn/opportunity numbers are never fabricated ahead of
    that. The rule-based math below is the pipeline's own internal fallback
    (see rule_engine.py); it's only surfaced here as a supporting detail
    *after* analysis has run, never as a substitute for running it."""
    analyzed = latest_rec is not None
    base = {
        "customer_id": customer["customer_id"],
        "company_name": customer["customer_name"],
        "industry": customer.get("industry"),
        "region": _stable_pick(customer["customer_id"], REGIONS),
        "plan_tier": _display_plan(customer.get("plan_tier"), cat_index),
        # The real catalog product name (e.g. "Badminton Starter Racket"),
        # never collapsed to the generic Starter/Pro/Enterprise vocabulary --
        # plan_tier is still useful for grouping/eligibility math, but the UI
        # should show this for "what does this customer actually have".
        "current_product": customer.get("current_product") or customer.get("plan_tier"),
        "seats": customer.get("seats"),
        "mrr": _mrr(customer, cat_index),
        "analyzed": analyzed,
        "data_gaps": _data_gaps(dataset_counts) if dataset_counts is not None else [],
    }
    if not analyzed:
        return {
            **base, "churn_score": None, "churn_segment": None, "total_opportunity": None,
            "has_recommendation": False, "no_recommendation_reason_code": None, "no_recommendation_reason": None,
            "retention_action": None,
            "retention_action_type": None,
            # Confidence is the list's sort key; None sinks unanalyzed rows to
            # the bottom (see list_customers).
            "recommended_product": None, "recommendation_type": None,
            "is_low_confidence_pitch": False, "confidence": None,
        }

    usage_rows = db.get_usage(tenant_id, customer["customer_id"])
    tickets = db.get_tickets(tenant_id, customer["customer_id"])
    adoption = _adoption_pct(customer, usage_rows)
    churn_score, _, _, _, _ = _churn(customer, usage_rows, tickets, adoption)

    # Risk category comes from the agent's own output (churn_risk), not the
    # local recompute -- the agent (or its internal rule fallback, if the
    # LLM call failed) is the source of truth once it has actually run.
    risk = (latest_rec.get("churn_risk") or "low").upper()
    churn_score = _reconcile_churn_score(churn_score, risk)
    opportunity = int(round(latest_rec["estimated_deal_value"])) if latest_rec.get("estimated_deal_value") else 0

    reason_code = latest_rec.get("no_recommendation_reason_code")
    has_recommendation = bool(latest_rec.get("recommended_product"))
    return {
        **base,
        "churn_score": churn_score,
        "churn_segment": risk,
        "total_opportunity": opportunity,
        "has_recommendation": has_recommendation,
        "no_recommendation_reason_code": reason_code,
        "no_recommendation_reason": _no_recommendation_reason(reason_code, latest_rec.get("churn_reason")),
        "retention_action": _retention_action(reason_code, latest_rec.get("retention_action")),
        "retention_action_type": (_retention_action_detail(reason_code, latest_rec.get("retention_action")) or {}).get("action_type"),
        # Persisted recommendation fields so the customer list is self-
        # sufficient (current -> recommended -> potential -> confidence)
        # straight from the last run, without re-analyzing each row.
        "recommended_product": latest_rec.get("recommended_product"),
        "recommendation_type": latest_rec.get("recommendation_type"),
        "is_low_confidence_pitch": bool(reason_code) and has_recommendation,
        "confidence": _stored_confidence(latest_rec),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/data-status")
def data_status(tenant_id: str = Depends(get_current_tenant)):
    """Tenant-wide view of what's actually been uploaded, so the UI can say
    "I don't have this data" up front instead of after a confusing analysis
    run."""
    counts = db.tenant_dataset_counts(tenant_id)
    customer_count = len(db.get_customers(tenant_id))
    return {
        "customers": customer_count,
        "usage_metrics_rows": counts.get("usage_metrics", 0),
        "support_tickets_rows": counts.get("support_tickets", 0),
        "product_catalog_rows": counts.get("product_catalog", 0),
        "product_catalog_is_demo_seed": counts.get("product_catalog", 0) == 0 and counts.get("product_catalog_demo_seed", 0) > 0,
        "gaps": _data_gaps(counts),
        "can_run_analysis": customer_count > 0 and counts.get("product_catalog", 0) > 0,
    }


@router.get("/catalog")
def get_catalog(tenant_id: str = Depends(get_current_tenant)):
    """
    Real per-tenant product catalog for the frontend's Upsell Catalog view.

    Replaces what used to be a hardcoded, SaaS-shaped list of 10 fake
    products (Enterprise Plan Upgrade, Extra Storage +500GB, etc.) baked
    into the frontend regardless of tenant. Every field here is either a
    raw catalog column for this tenant (product_name, category, tier_level,
    price_per_seat) or computed live against this tenant's actual customers
    (eligible_customers, potential_revenue) -- nothing is a
    hardcoded assumption about plan names or seat counts.

    `category` is whatever this tenant's catalog dataset actually has in
    that column (may be None if there's no such column at all -- see
    db._schema_free_product_catalog's note on this), so the frontend must
    not assume a fixed Upgrades/Add-ons/Complementary/Retention taxonomy.
    """
    catalog = db.get_product_catalog(tenant_id)
    cat_index = _catalog_index(catalog)
    customers = db.get_customers(tenant_id)
    counts = db.tenant_dataset_counts(tenant_id)

    # The category each customer currently "lives in" = the category of their
    # own current product/plan (looked up in the catalog by plan_tier). Used
    # to keep a product's eligible list inside its own product line, so
    # clicking e.g. a Badminton racket surfaces Badminton customers -- not
    # every customer in the base (a Cricket store is not a lead for a
    # Badminton upsell). categories_with_customers is the set of categories
    # customers actually own something in, so a standalone add-on/module
    # category no one's base plan belongs to still falls back to the whole
    # base instead of matching zero customers.
    def _customer_category(c):
        prod = cat_index.get(c.get("plan_tier"))
        return (prod.get("category") if prod else None)

    customer_categories = {c["customer_id"]: _customer_category(c) for c in customers}
    categories_with_customers = {v for v in customer_categories.values() if v}

    items = []
    for p in catalog:
        try:
            tier = int(p.get("tier_level"))
        except (TypeError, ValueError):
            continue
        price = float(p.get("price_per_seat") or 0)
        is_core_plan = p.get("category") == "core-plan"
        prod_category = p.get("category")

        # Scope to the product's own category when customers actually own
        # products in that category (its own line). Otherwise (a standalone
        # module/add-on category no customer's base plan belongs to) fall
        # back to the whole base so those products still surface leads.
        same_line = bool(prod_category and prod_category in categories_with_customers)
        if same_line:
            base_pool = [c for c in customers if customer_categories.get(c["customer_id"]) == prod_category]
        else:
            base_pool = customers

        if is_core_plan:
            # A genuine plan upgrade: eligible customers are the ones below
            # this tier, and the revenue opportunity is the price delta over
            # what they already pay (not the sticker price).
            eligible = [
                c for c in base_pool
                if _current_tier_level(c.get("plan_tier"), cat_index) < tier
            ]
            potential_revenue = sum(
                max(price - _plan_price(c.get("plan_tier"), cat_index), 0) * (c.get("seats") or 0)
                for c in eligible
            )
        elif same_line:
            # A product within a line the customer already owns from (e.g. a
            # higher-tier racket in the same sport): an upsell/cross-sell
            # within that line. Every customer in the line who isn't already
            # on this exact product is a candidate.
            eligible = [c for c in base_pool if c.get("plan_tier") != p.get("product_name")]
            potential_revenue = sum(price * (c.get("seats") or 0) for c in eligible)
        else:
            # An add-on/module: `tier_level` is the minimum plan tier
            # required to purchase it, not something to "upgrade into" --
            # eligible customers are ones who already qualify, and it's
            # fully incremental revenue on top of their existing plan.
            eligible = [
                c for c in base_pool
                if _current_tier_level(c.get("plan_tier"), cat_index) >= tier
            ]
            potential_revenue = sum(price * (c.get("seats") or 0) for c in eligible)

        items.append({
            "product_id": p.get("product_id"),
            "product_name": p.get("product_name"),
            "category": p.get("category"),
            "description": p.get("description"),
            "features": p.get("features"),
            "tier_level": tier,
            "price_per_seat": price,
            "eligible_customers": len(eligible),
            # Total seats across every eligible customer -- a real volume
            # figure that varies per product, unlike the account count which
            # clusters near the full customer base. This is the headline the
            # catalog UI shows ("N seats").
            "eligible_seats": int(sum((c.get("seats") or 0) for c in eligible)),
            "eligible_customer_ids": [c["customer_id"] for c in eligible],
            "potential_revenue": round(potential_revenue, 2),
            # True when this product's category didn't match any current
            # customer's own category, so `eligible` silently fell back to
            # the WHOLE tenant base instead of a real category-scoped pool.
            # Without this flag, a fallback-inflated count (e.g. "48 of 50
            # accounts eligible" for a brand-new product line nobody
            # actually stocks yet) looks identical to a real match on the
            # frontend -- see UpsellCatalog.jsx for how it's surfaced.
            "is_fallback_pool": not same_line,
        })

    items.sort(key=lambda x: (x["tier_level"], x["product_name"] or ""))
    tenant_config = db.get_tenant_config(tenant_id)
    return {
        "products": items,
        "is_demo_seed": counts.get("product_catalog", 0) == 0 and counts.get("product_catalog_demo_seed", 0) > 0,
        # "recurring" (SaaS -- potential_revenue is a valid /mo figure) or
        # "one_time" (retail/goods -- potential_revenue is a one-off sale
        # total, and labeling it "/mo" would fabricate recurring revenue
        # that doesn't exist). Defaults to "recurring" for tenants who
        # haven't set POST /tenant/{id}/config revenue_model explicitly.
        "revenue_model": tenant_config.get("revenue_model", "recurring"),
    }


@router.get("/customers")
def list_customers(tenant_id: str = Depends(get_current_tenant)):
    catalog = db.get_product_catalog(tenant_id)
    cat_index = _catalog_index(catalog)
    latest = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
    dataset_counts = db.tenant_dataset_counts(tenant_id)
    cards = [
        _customer_card(tenant_id, c, catalog, cat_index, latest.get(c["customer_id"]), dataset_counts)
        for c in db.get_customers(tenant_id)
    ]
    # Rank by how confident we are we can recommend to them; unanalyzed
    # (confidence None) sinks to the bottom.
    cards.sort(key=lambda c: (c.get("confidence") is None, -(c.get("confidence") or 0.0)))
    return cards


@router.get("/customers/{customer_id}")
def get_customer(customer_id: str, tenant_id: str = Depends(get_current_tenant)):
    customers = db.get_customers(tenant_id, [customer_id])
    if not customers:
        raise HTTPException(status_code=404, detail="Customer not found")
    catalog = db.get_product_catalog(tenant_id)
    cat_index = _catalog_index(catalog)
    latest = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
    dataset_counts = db.tenant_dataset_counts(tenant_id)
    return _customer_card(tenant_id, customers[0], catalog, cat_index, latest.get(customer_id), dataset_counts)


@router.get("/customers/{customer_id}/analysis")
def customer_analysis(customer_id: str, tenant_id: str = Depends(get_current_tenant)):
    customers = db.get_customers(tenant_id, [customer_id])
    if not customers:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer = customers[0]
    catalog = db.get_product_catalog(tenant_id)
    cat_index = _catalog_index(catalog)

    latest_recs = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
    latest_rec = latest_recs.get(customer_id)
    dataset_counts = db.tenant_dataset_counts(tenant_id)
    gaps = _data_gaps(dataset_counts)
    can_run_analysis = dataset_counts.get("product_catalog", 0) > 0

    # Nothing to show until the agent pipeline has actually produced a
    # result for this customer. Rule-based math is the pipeline's internal
    # fallback for when the LLM call fails -- it is never a stand-in for
    # analysis that the user hasn't run yet.
    if not latest_rec:
        return {
            "customer_id": customer_id,
            "analyzed": False,
            "data_gaps": gaps,
            "can_run_analysis": can_run_analysis,
            # Stage 5 (schema_free_pipeline_design.md §5): generic insight
            # list, additive alongside the fixed fields below. Available
            # even before a full pipeline run -- churn_risk/revenue_opportunity
            # fall back to conservative local estimates rather than being
            # omitted, since they're core insights (see app/insights.py).
            "insights": build_customer_insights(
                tenant_id, customer, db.get_usage(tenant_id, customer_id),
                db.get_tickets(tenant_id, customer_id), catalog, None,
            ),
            "customer_summary": {
                "company_name": customer["customer_name"],
                "industry": customer.get("industry"),
                "region": _stable_pick(customer_id, REGIONS),
                "plan_tier": _display_plan(customer.get("plan_tier"), cat_index),
                "current_product": customer.get("plan_tier"),
                "seats": customer.get("seats"),
                "mrr": _mrr(customer, cat_index),
                "days_to_renewal": days_to_renewal(customer["renewal_date"]),
            },
        }

    usage_rows = db.get_usage(tenant_id, customer_id)
    tickets = db.get_tickets(tenant_id, customer_id)

    adoption = _adoption_pct(customer, usage_rows)
    churn_score, local_risk, factor_breakdown, trend, renewal_days = _churn(
        customer, usage_rows, tickets, adoption
    )
    # Risk category + explanation come from the agent's own output, not the
    # local recompute -- see note in _customer_card.
    risk = (latest_rec.get("churn_risk") or local_risk).upper()
    # The badge (risk) and the number (churn_score) come from two different
    # sources of truth (agent verdict vs. local deterministic formula) --
    # reconcile them so a customer never sees e.g. "HIGH CHURN" next to a
    # score their own scale would call MEDIUM.
    churn_score = _reconcile_churn_score(churn_score, risk)
    opportunity = int(round(latest_rec.get("estimated_deal_value") or 0))

    churn_analysis = {
        "risk_level": risk,
        "churn_score": churn_score,
        "explanation": latest_rec.get("churn_reason") or _churn_explanation(risk, trend, renewal_days, tickets, adoption),
        "factor_breakdown": factor_breakdown,
    }

    has_recommendation = bool(latest_rec.get("recommended_product"))
    reason_code = latest_rec.get("no_recommendation_reason_code")
    # A reason_code can still be set even though we now always fill in a
    # product -- that combination means "this is a low-confidence general
    # pitch, not a high-conviction match" (see workflow.py's fallback pitch).
    is_low_confidence_pitch = bool(reason_code) and has_recommendation
    retention_action = _retention_action(reason_code, latest_rec.get("retention_action"))
    retention_action_detail = _retention_action_detail(reason_code, latest_rec.get("retention_action"))
    confidence = _stored_confidence(latest_rec)

    agent_trace = _parse_agent_trace(latest_rec.get("agent_trace")) if latest_rec else None
    trace = _trace_from_agent_trace(agent_trace)

    all_recommendations = []
    seen_products = set()
    if has_recommendation:
        rec_prod = latest_rec.get("recommended_product")
        seen_products.add(rec_prod)
        all_recommendations.append({
            "id": latest_rec.get("id"),
            "recommended_product": rec_prod,
            "type": latest_rec.get("recommendation_type") or "upsell",
            "revenue_opportunity": opportunity,
            "rationale": latest_rec.get("rationale"),
            "confidence": confidence,
            "is_low_confidence_pitch": is_low_confidence_pitch,
            "segment": latest_rec.get("segment"),
            "status": _feedback_status(latest_rec.get("outcome")),
        })
        
    # Trust invariant: NEVER invent secondary recommendations from the catalog.
    # Only audited results from the recommendation pipeline appear in this list.

    return {
        "customer_id": customer_id,
        "analyzed": True,
        "has_recommendation": has_recommendation,
        "no_recommendation_reason_code": reason_code,
        "retention_action": retention_action,
        "retention_action_detail": retention_action_detail,
        "confidence": confidence,
        "data_gaps": gaps,
        "customer_summary": {
            "company_name": customer["customer_name"],
            "industry": customer.get("industry"),
            "plan_tier": _display_plan(customer.get("plan_tier"), cat_index),
            "current_product": customer.get("plan_tier"),
            "seats": customer.get("seats"),
            "days_to_renewal": renewal_days,
        },
        "churn_analysis": churn_analysis,
        # Dataset-driven insight list (app/insights.py): the metrics that
        # actually matter for THIS tenant's data, surfaced generically. This
        # is now the ONLY metrics surface on the detail view -- it replaces the
        # old fabricated NPS/CSAT/bandwidth/business-impact/next-actions blocks
        # that used to be computed and returned here.
        "insights": build_customer_insights(
            tenant_id, customer, usage_rows, tickets, catalog, latest_rec,
        ),
        "all_recommendations": all_recommendations,
        "decision_status": (agent_trace or {}).get("decision_status", "unverified"),
        "evidence": (agent_trace or {}).get("evidence", []),
        "trace": trace,
    }


def _matrix_label(bandwidth: int, revenue_opportunity: int) -> str:
    high_rev = revenue_opportunity >= 2000
    if bandwidth >= 70:
        return "Priority Upsell" if high_rev else "Cross-Sell"
    if bandwidth >= 40:
        return "Right-Size" if high_rev else "Feature Nudge"
    return "Retention First" if high_rev else "Re-Engagement"


def _churn_explanation(risk, trend, renewal_days, tickets, adoption) -> str:
    parts = []
    if trend < 0:
        parts.append(f"usage is down {abs(trend):.0f}%")
    elif trend > 0:
        parts.append(f"usage is up {trend:.0f}%")
    else:
        parts.append("usage is flat")
    parts.append(f"renewal in {renewal_days} days")
    open_tickets = [t for t in tickets if not t.get("resolved")]
    if open_tickets:
        parts.append(f"{len(open_tickets)} open support ticket(s)")
    parts.append(f"feature adoption at {adoption}%")
    return f"{risk} churn risk: " + ", ".join(parts) + "."


def _immediate_action(risk, bandwidth) -> str:
    if risk == "HIGH":
        return "Retention outreach"
    if bandwidth >= 70:
        return "Expansion offer"
    if bandwidth >= 40:
        return "Feature adoption nudge"
    return "Monitor & re-engage"


def _business_impact(opportunity: int, risk: str, adoption: int, csat: float, mrr: float) -> dict:
    """Deterministic 'Business Impact' block for the customer analysis view."""
    ltv = int(round(mrr * 36))  # ~3-year expected lifetime value
    retention = (
        "Protects existing ARR" if risk == "HIGH"
        else "Stable renewal outlook" if risk == "MEDIUM"
        else "Strong retention"
    )
    adoption_impact = (
        "High upside" if adoption < 40
        else "Moderate upside" if adoption < 70
        else "Near saturation"
    )
    return {
        "additional_revenue": f"${opportunity:,}/yr",
        "retention_impact": retention,
        "adoption_impact": adoption_impact,
        "satisfaction_impact": f"CSAT {csat}/5",
        "lifetime_value": f"${ltv:,}",
    }


def _next_actions(risk: str, bandwidth: int, adoption: int, renewal_days: int, nxt: dict | None,
                  adoption_available: bool = True) -> list[dict]:
    """Deterministic 'Recommended Next Actions' list ({urgency, action, reason, owner}).

    `adoption_available` guards the feature-onboarding action: when a tenant
    has no real feature-usage/adoption signal, `_adoption_pct` returns a
    fabricated 0%, which would otherwise make "Drive feature onboarding"
    fire for EVERY customer off data that doesn't exist. Only suggest it
    when we actually measured low adoption, not when we simply have no data.
    """
    actions = []
    if risk == "HIGH":
        actions.append({
            "urgency": "Critical",
            "action": "Schedule a retention / save call",
            "reason": "High churn risk from usage and support signals.",
            "owner": "CSM",
        })
    if renewal_days <= 90:
        actions.append({
            "urgency": "High",
            "action": "Start the renewal conversation early",
            "reason": f"Renewal is {renewal_days} days away.",
            "owner": "CSM",
        })
    if risk != "HIGH" and bandwidth >= 70 and nxt:
        actions.append({
            "urgency": "High",
            "action": f"Present upgrade to {nxt['product_name']}",
            "reason": f"Capacity usage at {bandwidth}% supports expansion.",
            "owner": "Account Executive",
        })
    if adoption_available and adoption < 40:
        actions.append({
            "urgency": "Medium",
            "action": "Drive feature onboarding",
            "reason": f"Feature adoption is only {adoption}%.",
            "owner": "Onboarding",
        })
    if not actions:
        actions.append({
            "urgency": "Low",
            "action": "Monitor account health",
            "reason": "No urgent signals this period.",
            "owner": "CSM",
        })
    return actions


def _feedback_status(outcome) -> str:
    if outcome in ("accepted", "converted"):
        return "accepted"
    if outcome == "rejected":
        return "rejected"
    return "pending"


class GenerateResult(BaseModel):
    customer_id: str
    segment: str
    churn_score: int
    revenue_opportunity: int
    recommended_product: str | None = None


@router.post("/generate-recommendations")
def generate(customer_id: str | None = Query(default=None), segment: str | None = Query(default=None), tenant_id: str = Depends(get_current_tenant)):
    """Runs the reasoning pipeline. With customer_id, analyzes just that one
    account (force-included so it always returns a result); otherwise runs a
    full batch. Returns per-customer results plus the reasoning trace of the
    first result, in the shape the frontend expects."""
    catalog = db.get_product_catalog(tenant_id)
    cat_index = _catalog_index(catalog)
    dataset_counts = db.tenant_dataset_counts(tenant_id)

    # Without THIS TENANT'S OWN product catalog there is nothing to
    # recommend an upgrade or add-on *to* -- running anyway would silently
    # produce empty/zero results that look like "no opportunity found"
    # rather than "I don't have enough data to tell you that." Fail loudly
    # instead. db.get_product_catalog() above can return rows even when
    # nothing was uploaded, because app/onboarding.py auto-seeds a shared
    # demo catalog (source='demo_seed') for any new tenant that has none --
    # that's a standalone-demo convenience, not real tenant data, so it must
    # never satisfy this check. Only source='upload' rows (real ingestion
    # via app/data_ingestion.py, from a product_catalog.csv actually placed
    # under data/tenant_uploads/<tenant_id>/) count here.
    if dataset_counts.get("product_catalog", 0) == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No product catalog uploaded for tenant '{tenant_id}'. Analysis stopped -- "
                   f"please add a product_catalog.csv under data/tenant_uploads/{tenant_id}/ "
                   f"(and ingest it) before running analysis for this tenant.",
        )

    if customer_id:
        if not db.get_customers(tenant_id, [customer_id]):
            raise HTTPException(status_code=404, detail="Customer not found")
        recs = generate_recommendations(
            customer_ids=[customer_id],
            tenant_id=tenant_id,
            force_include=True,
            include_null_results=True,
        )
    else:
        recs = generate_recommendations(tenant_id=tenant_id)

    results = []
    first_trace = []
    for i, rec in enumerate(recs):
        cust = db.get_customers(tenant_id, [rec["customer_id"]])
        cust = cust[0] if cust else None
        usage_rows = db.get_usage(tenant_id, rec["customer_id"])
        tickets = db.get_tickets(tenant_id, rec["customer_id"])
        adoption = _adoption_pct(cust, usage_rows) if cust else 0
        churn_score, risk, _, _, _ = (
            _churn(cust, usage_rows, tickets, adoption) if cust else (0, "LOW", {}, 0, 0)
        )
        opportunity = int(round(rec.get("estimated_deal_value") or 0)) if rec.get("recommended_product") else 0
        reason_code = rec.get("no_recommendation_reason_code")
        results.append({
            "customer_id": rec["customer_id"],
            "segment": risk,
            "churn_score": churn_score,
            "revenue_opportunity": opportunity,
            "recommended_product": rec.get("recommended_product"),
            "confidence": _stored_confidence(rec),
            "is_low_confidence_pitch": bool(reason_code) and bool(rec.get("recommended_product")),
            "no_recommendation_reason_code": reason_code,
            "retention_action": _retention_action(reason_code, rec.get("retention_action")),
        })
        if i == 0:
            first_trace = _trace_from_agent_trace(_parse_agent_trace(rec.get("agent_trace")))

    return {"count": len(results), "results": results, "trace": first_trace}


@router.get("/recommendations/{customer_id}")
def recommendations_for_customer(customer_id: str, tenant_id: str = Depends(get_current_tenant)):
    catalog = db.get_product_catalog(tenant_id)
    latest = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
    rec = latest.get(customer_id)
    if not rec:
        return []
    is_pitch = bool(rec.get("no_recommendation_reason_code")) and bool(rec.get("recommended_product"))
    confidence = _stored_confidence(rec)
    return [{
        "id": rec.get("id"),
        "customer_id": rec.get("customer_id"),
        "type": rec.get("recommendation_type") or "upsell",
        "title": rec.get("recommended_product") or "No recommendation",
        "recommended_product": rec.get("recommended_product"),
        "justification": rec.get("rationale"),
        "revenue_opportunity": int(round(rec.get("estimated_deal_value") or 0)),
        "confidence": confidence,
        "is_low_confidence_pitch": is_pitch,
        "status": _feedback_status(rec.get("outcome")),
        "segment": rec.get("segment"),
    }]


class FeedbackBody(BaseModel):
    status: str


@router.post("/recommendations/{rec_id}/feedback")
def submit_feedback(rec_id: int, body: FeedbackBody, tenant_id: str = Depends(get_current_tenant)):
    status = body.status
    outcome = "accepted" if status == "accepted" else "rejected" if status == "rejected" else status
    if outcome not in ("accepted", "rejected", "converted"):
        raise HTTPException(status_code=400, detail="Invalid feedback status")
    if not db.get_recommendation_by_id(tenant_id, rec_id):
        raise HTTPException(status_code=404, detail="Recommendation not found")
    db.update_outcome(tenant_id, rec_id, outcome)
    return {"status": "ok", "id": rec_id, "outcome": outcome}


@router.get("/analytics/summary")
def analytics_summary(tenant_id: str = Depends(get_current_tenant)):
    catalog = db.get_product_catalog(tenant_id)
    cat_index = _catalog_index(catalog)
    latest = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
    dataset_counts = db.tenant_dataset_counts(tenant_id)

    dist = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    total_opportunity = 0
    cards = []
    all_customers = db.get_customers(tenant_id)
    for c in all_customers:
        card = _customer_card(tenant_id, c, catalog, cat_index, latest.get(c["customer_id"]), dataset_counts)
        if card["analyzed"]:
            dist[card["churn_segment"]] = dist.get(card["churn_segment"], 0) + 1
            total_opportunity += card["total_opportunity"]
        cards.append(card)

    analyzed_cards = [c for c in cards if c["analyzed"]]
    recommended_cards = [c for c in analyzed_cards if c["has_recommendation"]]
    no_rec_cards = [c for c in analyzed_cards if not c["has_recommendation"]]
    top_customers = sorted(recommended_cards, key=lambda x: x["total_opportunity"], reverse=True)[:5]

    # Conversion funnel: group logged recommendations by segment + outcome.
    funnel_counts = {}
    for rec in db.get_latest_recommendations(tenant_id):
        seg = (rec.get("churn_risk") or "").upper()
        seg = seg if seg in ("HIGH", "MEDIUM", "LOW") else "LOW"
        status = _feedback_status(rec.get("outcome"))
        funnel_counts[(seg, status)] = funnel_counts.get((seg, status), 0) + 1
    conversion_funnel = [
        {"segment": seg, "status": status, "count": count}
        for (seg, status), count in funnel_counts.items()
    ]

    return {
        "total_customers": len(all_customers),
        "analyzed_customers": len(analyzed_cards),
        "recommendations_generated": len(recommended_cards),
        "no_recommendation_customers": [
            {"customer_id": c["customer_id"], "company_name": c["company_name"],
             "churn_segment": c["churn_segment"], "no_recommendation_reason": c.get("no_recommendation_reason"),
             "retention_action": c["retention_action"], "retention_action_type": c.get("retention_action_type"),
             "current_product": c.get("current_product")}
            for c in no_rec_cards
        ],
        "data_gaps": _data_gaps(dataset_counts),
        "churn_distribution": [
            {"segment": seg, "count": dist[seg]} for seg in ("HIGH", "MEDIUM", "LOW")
        ],
        "total_revenue_opportunity": total_opportunity,
        "top_customers": [
            {"company_name": c["company_name"], "opportunity": c["total_opportunity"]}
            for c in top_customers
        ],
        "conversion_funnel": conversion_funnel,
    }


# ---------------------------------------------------------------------------
# Chat agent endpoints
# ---------------------------------------------------------------------------
from app.chat_agent import (
    process_message as _process_chat_message,
    list_sessions as _list_sessions,
    clear_session as _clear_session,
    get_session_history as _get_session_history,
)


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    customer_id: str | None = None


@router.post("/chat")
def chat(body: ChatRequest, tenant_id: str = Depends(get_current_tenant)):
    """Conversational AI agent endpoint."""
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")
    return _process_chat_message(
        message=body.message.strip(),
        tenant_id=tenant_id,
        conversation_id=body.conversation_id,
        hint_customer_id=body.customer_id,
    )


@router.get("/chat/sessions")
def list_chat_sessions(tenant_id: str = Depends(get_current_tenant)):
    return _list_sessions(tenant_id)


@router.delete("/chat/sessions/{conversation_id}")
def delete_chat_session(conversation_id: str, tenant_id: str = Depends(get_current_tenant)):
    if _clear_session(conversation_id, tenant_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Session not found")

@router.get("/chat/sessions/{conversation_id}")
def get_chat_session(conversation_id: str, tenant_id: str = Depends(get_current_tenant)):
    history = _get_session_history(conversation_id, tenant_id)
    if not history:
        raise HTTPException(status_code=404, detail="Session not found or empty")
    return history


# ---------------------------------------------------------------------------
# Email sending endpoints
# ---------------------------------------------------------------------------
from app.email_service import (
    send_recommendation_email as _send_rec_email,
    send_meeting_invite_email as _send_meeting_email,
)
import os
import requests


class SendEmailRequest(BaseModel):
    to_email: str
    sender_name: str | None = None


@router.post("/customers/{customer_id}/send-recommendation-email")
def send_recommendation_email_endpoint(
    customer_id: str, body: SendEmailRequest, tenant_id: str = Depends(get_current_tenant)
):
    customers = db.get_customers(tenant_id, [customer_id])
    if not customers:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer = customers[0]
    latest_recs = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
    rec = latest_recs.get(customer_id)
    if not rec or not rec.get("recommended_product"):
        raise HTTPException(status_code=400, detail="No recommendation available. Run analysis first.")
    try:
        return _send_rec_email(
            to_email=body.to_email,
            customer_name=customer.get("customer_name", customer_id),
            recommended_product=rec["recommended_product"],
            rationale=rec.get("rationale", ""),
            confidence_pct=int((rec.get("confidence") or 0) * 100),
            revenue_opportunity=int(round(rec.get("estimated_deal_value") or 0)),
            sender_name=body.sender_name or "Your Account Manager",
        )
    except EnvironmentError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e}")
@router.post("/customers/{customer_id}/trigger-email")
def trigger_power_automate_email_endpoint(
    customer_id: str, tenant_id: str = Depends(get_current_tenant)
):
    url = os.getenv("POWER_AUTOMATE_WEBHOOK_URL")
    if not url:
        raise HTTPException(status_code=503, detail="POWER_AUTOMATE_WEBHOOK_URL is not set in backend .env")
        
    customers = db.get_customers(tenant_id, [customer_id])
    if not customers:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer = customers[0]
    
    latest_recs = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
    rec = latest_recs.get(customer_id)
    
    payload = {
        "source": "Upsell Recommendation Agent",
        "customer": {
            "customer_id": customer.get("customer_id") or customer_id,
            "company_name": customer.get("customer_name") or customer.get("company_name", customer_id),
            "recommended_product": rec.get("recommended_product") if rec else None,
            "confidence": rec.get("confidence") if rec else None
        }
    }
    
    try:
        res = requests.post(
            url, 
            json=payload, 
            headers={"Content-Type": "application/json"}
        )
        res.raise_for_status()
        return {"status": "triggered"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to trigger Power Automate: {e}")


class BatchSendEmailRequest(BaseModel):
    to_email_map: dict
    sender_name: str | None = None


@router.post("/batch/send-emails")
def batch_send_emails(body: BatchSendEmailRequest, tenant_id: str = Depends(get_current_tenant)):
    latest_recs = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
    results = []; sent = 0; failed = 0
    for cid, to_email in body.to_email_map.items():
        rec = latest_recs.get(cid)
        if not rec or not rec.get("recommended_product"):
            results.append({"customer_id": cid, "status": "skipped"}); continue
        custs = db.get_customers(tenant_id, [cid])
        customer = custs[0] if custs else {"customer_name": cid}
        try:
            _send_rec_email(
                to_email=to_email,
                customer_name=customer.get("customer_name", cid),
                recommended_product=rec["recommended_product"],
                rationale=rec.get("rationale", ""),
                confidence_pct=int((rec.get("confidence") or 0) * 100),
                revenue_opportunity=int(round(rec.get("estimated_deal_value") or 0)),
                sender_name=body.sender_name or "Your Account Manager",
            )
            results.append({"customer_id": cid, "status": "sent", "to": to_email}); sent += 1
        except Exception as e:
            results.append({"customer_id": cid, "status": "failed", "error": str(e)}); failed += 1
    return {"sent": sent, "failed": failed, "results": results}


# ---------------------------------------------------------------------------
# Meeting scheduling endpoint
# ---------------------------------------------------------------------------
from app.meeting_service import schedule_meeting as _schedule_meeting


class ScheduleMeetingRequest(BaseModel):
    title: str
    datetime_utc: str
    attendee_email: str
    duration_minutes: int = 30
    agenda: str | None = None
    send_email: bool = True
    sender_name: str | None = None


@router.post("/customers/{customer_id}/schedule-meeting")
def schedule_meeting_endpoint(
    customer_id: str, body: ScheduleMeetingRequest, tenant_id: str = Depends(get_current_tenant)
):
    customers = db.get_customers(tenant_id, [customer_id])
    if not customers:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer = customers[0]
    meeting = _schedule_meeting(
        title=body.title, start_datetime_utc=body.datetime_utc,
        attendee_email=body.attendee_email, duration_minutes=body.duration_minutes,
        agenda=body.agenda, customer_name=customer.get("customer_name"),
    )
    if body.send_email and meeting.get("meet_link"):
        try:
            _send_meeting_email(
                to_email=body.attendee_email,
                customer_name=customer.get("customer_name", customer_id),
                meeting_title=body.title, meeting_datetime=body.datetime_utc,
                meet_link=meeting["meet_link"], agenda=body.agenda,
                sender_name=body.sender_name or "Your Account Manager",
            )
            meeting["email_sent"] = True
        except Exception as e:
            meeting["email_sent"] = False; meeting["email_error"] = str(e)
    return meeting


# ---------------------------------------------------------------------------
# Catalog CRUD endpoints
# ---------------------------------------------------------------------------
class AddProductRequest(BaseModel):
    product_name: str
    category: str | None = None
    tier_level: int = 1
    price_per_seat: float = 0.0
    description: str | None = None


class UpdateProductRequest(BaseModel):
    product_name: str | None = None
    category: str | None = None
    tier_level: int | None = None
    price_per_seat: float | None = None
    description: str | None = None


@router.post("/catalog/products")
def add_catalog_product_endpoint(body: AddProductRequest, tenant_id: str = Depends(get_current_tenant)):
    product = db.add_catalog_product(
        tenant_id=tenant_id, product_name=body.product_name,
        category=body.category or "custom", tier_level=body.tier_level,
        price_per_seat=body.price_per_seat, description=body.description,
    )
    return {"status": "created", "product": product}


@router.delete("/catalog/products/{product_id}")
def delete_catalog_product_endpoint(product_id: int, tenant_id: str = Depends(get_current_tenant)):
    ok = db.remove_catalog_product(tenant_id, product_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"status": "deleted", "product_id": product_id}


@router.patch("/catalog/products/{product_id}")
def update_catalog_product_endpoint(
    product_id: int, body: UpdateProductRequest, tenant_id: str = Depends(get_current_tenant)
):
    updated = db.update_catalog_product(tenant_id, product_id, {k: v for k, v in body.dict().items() if v is not None})
    if not updated:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"status": "updated", "product": updated}


# ---------------------------------------------------------------------------
# Feature weights endpoints
# ---------------------------------------------------------------------------
class FeatureWeightsRequest(BaseModel):
    weights: dict


@router.get("/tenant/feature-weights")
def get_feature_weights_endpoint(tenant_id: str = Depends(get_current_tenant)):
    return {"tenant_id": tenant_id, "weights": db.get_feature_weights(tenant_id)}


@router.post("/tenant/feature-weights")
def set_feature_weights_endpoint(body: FeatureWeightsRequest, tenant_id: str = Depends(get_current_tenant)):
    for name, w in body.weights.items():
        if not isinstance(w, (int, float)) or float(w) < 0 or float(w) > 5:
            raise HTTPException(status_code=400, detail=f"Weight for '{name}' must be 0-5")
    updated = db.set_feature_weights(tenant_id, body.weights)
    return {"status": "ok", "tenant_id": tenant_id, "weights": updated}