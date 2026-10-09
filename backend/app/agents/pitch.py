"""
Deterministic, LLM-free catalog pitch selection.

Kept in its own module with NO IndiaAI client / LLM imports on purpose, so
both the multi-agent workflow (app/agents/workflow.py) AND the batch
pipeline (app/pipeline.py) can build a catalog-backed "low-confidence pitch"
for a customer without pulling in the agent stack. The pipeline uses this to
give EVERY customer a product/cross-sell suggestion with a confidence score
-- including the ones the cheap prefilter never shortlisted for the full
agent run -- so no customer ever surfaces as a bare "no recommendation".
"""

from datetime import datetime

from app.prefilter import estimate_churn_risk


def tier_of(product: dict) -> int | None:
    """Catalog tier level as an int, or None if the product carries no
    usable tier (so callers can tell 'entry tier' apart from 'unknown')."""
    try:
        return int(product.get("tier_level"))
    except (TypeError, ValueError):
        return None


def catalog_lookup(catalog: list[dict], product_name: str | None) -> dict | None:
    if not product_name:
        return None
    return next((p for p in catalog if p.get("product_name") == product_name), None)


def classify_rec_type(catalog: list[dict], current_product: str | None, recommended_product: str | None) -> str:
    """Label a confident recommendation as an upgrade vs a cross-sell using
    the tenant's own catalog tiers: a product at a HIGHER tier than the
    customer's current plan is an upsell/upgrade; anything at the same or a
    different (non-higher) tier is treated as a cross-sell. Purely catalog-
    driven, so the labelling varies naturally by tenant/industry."""
    current = catalog_lookup(catalog, current_product)
    rec = catalog_lookup(catalog, recommended_product)
    current_tier = tier_of(current) if current else None
    rec_tier = tier_of(rec) if rec else None
    if current_tier is not None and rec_tier is not None and rec_tier > current_tier:
        return "upsell"
    return "cross_sell"


def pitch_from_catalog(catalog: list[dict], candidate_products: list | None = None, current_product: str | None = None):
    """
    Always have *something useful* to show the CSM/rep, even when the
    pipeline found no strong opportunity -- a rep-facing "no recommendation"
    is never actionable. But the pitch must be a plausible *next step* for
    this specific account, not just the first (cheapest, tier-1 "Starter")
    row in the catalog, which is what a naive `catalog[0]` fallback produced
    for every account regardless of industry or current plan.

    Selection order, each grounded in the tenant's own catalog so the pitch
    naturally varies by dataset/industry:
      1. Upgrade -- the cheapest product a tier ABOVE the customer's current
         plan (preferring the same category / a core-plan line), i.e. a real
         upsell path rather than a lateral or downgrade suggestion.
      2. Cross-sell -- a complement of the current product (from the catalog's
         `complements`/`cross_sell` field) the customer doesn't already have.
      3. Relevance -- the top vector-ranked candidate the retrieval step
         already produced for this account (ordered by the customer's signals).
      4. Last resort -- any catalog product above entry tier that isn't the
         current plan (skip tier-1 "Starter/entry" items unless nothing else
         exists), so a fallback still reads as a step up.

    `current_product` (the customer's own plan_tier) is always excluded --
    pitching a customer the plan they already have is never useful.

    Returns a dict {product_name, price, reason, rec_type, label, score} or
    None if there's truly no catalog to pull from. `rec_type` is a
    frontend-styling key ("upsell"/"cross_sell"); `label` is the human word
    used in rationale text; `score` is a low-confidence revenue_score.
    """
    def _pick(item):
        if isinstance(item, dict):
            return item.get("product_name"), float(item.get("price_per_seat") or 0)
        return getattr(item, "product_name", None), float(getattr(item, "price_per_seat", None) or 0)

    current = catalog_lookup(catalog, current_product)
    current_tier = tier_of(current) if current else None
    current_cat = (current.get("category") or "").lower() if current else None

    # 1) Genuine upgrade: cheapest product strictly above the current tier.
    if current_tier is not None:
        higher = [
            p for p in catalog
            if p.get("product_name") and p.get("product_name") != current_product
            and (tier_of(p) or 0) > current_tier
        ]
        if higher:
            same_cat = [p for p in higher if current_cat and (p.get("category") or "").lower() == current_cat]
            core = [p for p in higher if (p.get("category") or "").lower() in ("core-plan", "core", "plan")]
            pool = same_cat or core or higher
            best = min(pool, key=lambda p: ((tier_of(p) or 99), float(p.get("price_per_seat") or 0)))
            name, price = _pick(best)
            return {
                "product_name": name, "price": price,
                "reason": f"a natural upgrade from {current_product}, matching this account's plan progression",
                "rec_type": "upsell", "label": "upgrade", "score": 35,
            }

    # 2) Cross-sell: a complement of the current product they don't have yet.
    if current:
        complements_raw = current.get("complements") or current.get("cross_sell") or ""
        for name in [c.strip() for c in str(complements_raw).split(",") if c.strip()]:
            comp = catalog_lookup(catalog, name)
            if comp and comp.get("product_name") != current_product:
                cname, cprice = _pick(comp)
                return {
                    "product_name": cname, "price": cprice,
                    "reason": f"frequently bought alongside {current_product}",
                    "rec_type": "cross_sell", "label": "cross-sell", "score": 30,
                }

    # 3) Relevance: the top candidate the retrieval step ranked for this account.
    if candidate_products:
        for item in candidate_products:
            name, price = _pick(item)
            if name and name != current_product:
                return {
                    "product_name": name, "price": price,
                    "reason": "the closest match in the catalog to this account's usage and support signals",
                    "rec_type": "cross_sell", "label": "cross-sell", "score": 25,
                }

    # 4) Last resort: a step up from entry tier, avoiding a tier-1 "Starter".
    pool = [p for p in catalog if p.get("product_name") and p.get("product_name") != current_product]
    if pool:
        above_entry = [p for p in pool if (tier_of(p) or 1) > 1]
        chosen = min(above_entry or pool, key=lambda p: float(p.get("price_per_seat") or 0))
        name, price = _pick(chosen)
        return {
            "product_name": name, "price": price,
            "reason": "a higher-value option from the catalog to explore with this account",
            "rec_type": "cross_sell", "label": "cross-sell", "score": 20,
        }
    return None


def build_pitch_recommendation(
    customer: dict,
    catalog: list[dict],
    reason_code: str = "not_shortlisted",
    reason_text: str | None = None,
    usage_rows: list[dict] | None = None,
    tickets: list[dict] | None = None,
) -> dict:
    """
    Build a complete, DB-shaped recommendation dict for a customer using only
    the catalog -- no LLM call. Used by the batch pipeline for customers the
    prefilter didn't shortlist, so every customer still gets a product/cross-
    sell suggestion carrying an honest low confidence score rather than a bare
    "no recommendation". The returned dict matches the field shape
    db.log_recommendation and web_api expect.

    churn_risk is computed from the same deterministic rule the rule engine
    uses (app.prefilter.estimate_churn_risk), not hardcoded -- a customer can
    land here specifically because their usage is declining (the prefilter's
    trend check only shortlists on *growth*, not decline), so this is exactly
    the population most likely to include real high-churn accounts.
    """
    renewal = customer.get("renewal_date")
    renewal_iso = renewal.isoformat() if hasattr(renewal, "isoformat") else renewal
    churn_risk, churn_risk_reason = estimate_churn_risk(customer, usage_rows or [], tickets or [])
    # Hard code-level gate, same as the rule engine and agent workflow:
    # never surface an upsell pitch for a high-churn account -- retention
    # comes first.
    pitch = None if churn_risk == "high" else pitch_from_catalog(catalog, current_product=customer.get("plan_tier"))
    effective_reason_code = "high_churn_gate" if churn_risk == "high" else reason_code

    base = {
        "customer_id": customer["customer_id"],
        "customer_name": customer.get("customer_name") or customer["customer_id"],
        "segment": "not_shortlisted",
        "churn_risk": churn_risk,
        "renewal_date": renewal_iso,
        "generated_at": datetime.utcnow().isoformat(),
        "no_recommendation_reason_code": effective_reason_code,
        "agent_trace": {
            "agents_run": [],
            "outcome": "low_confidence_pitch",
            "retrieval_method": "deterministic_catalog_pitch",
            "fallbacks_used": [],
        },
    }

    if not pitch:
        # Truly no catalog to pull from -- there's nothing to suggest.
        base.update({
            "recommended_product": None,
            "recommendation_type": None,
            "is_low_confidence_pitch": False,
            "churn_reason": reason_text or churn_risk_reason,
            "rationale": reason_text or "No catalog products available to suggest.",
            "revenue_score": 0,
            "confidence": 0.0,
            "estimated_deal_value": 0,
        })
        return base

    seats = customer.get("seats") or 0
    estimated_deal_value = round((pitch["price"] or 0) * seats * 12, 2) if seats else 0
    base.update({
        "recommended_product": pitch["product_name"],
        "recommendation_type": pitch["rec_type"],
        "is_low_confidence_pitch": True,
        "churn_reason": reason_text or churn_risk_reason,
        "rationale": (
            f"Suggested {pitch['label']}: {pitch['product_name']} -- {pitch['reason']}. "
            f"Low-confidence suggestion (not shortlisted this cycle) rather than a strong, data-backed match."
        ),
        "revenue_score": pitch["score"],
        # A deterministic "starting point" pitch for a customer the prefilter
        # never shortlisted -- honestly low confidence, never a data-backed match.
        "confidence": 0.15,
        "estimated_deal_value": estimated_deal_value,
    })
    return base
