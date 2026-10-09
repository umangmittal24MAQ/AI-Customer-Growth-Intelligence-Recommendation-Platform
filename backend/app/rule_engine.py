"""
Rule-Based Reasoning Agent — the default recommendation engine. Fully
deterministic, zero cost, no API key required. This is what makes the
product work immediately for anyone who downloads it.

The LLM path (llm_engine.py) is an OPTIONAL upgrade a tenant can enable for
richer, more nuanced rationale text — never a hard requirement.
"""

from app.prefilter import compute_usage_trend, storage_pct_used, has_relevant_ticket, days_to_renewal, estimate_churn_risk


def _top_service_note(service_rows: list[dict] = None) -> str:
    """Names the single most-used service for the latest month in
    service_rows, if provided -- makes the rationale concrete ('driven
    largely by Analytics Dashboard usage') instead of just citing a percent,
    and is citable back to service_usage rows rather than an opaque score.
    Returns "" if service_rows is None/empty -- this is optional detail,
    never required for the rule engine to function."""
    if not service_rows:
        return ""
    latest_month = service_rows[0]["month"]
    latest_rows = [r for r in service_rows if r["month"] == latest_month and r.get("usage_count") is not None]
    if not latest_rows:
        return ""
    top = max(latest_rows, key=lambda r: r["usage_count"])
    return f" (driven largely by {top['service_name']} usage)"


def pick_next_tier_product(current_plan: str, catalog: list[dict]) -> dict | None:
    """Finds the next tier up from the customer's current plan in the catalog."""
    current = next((p for p in catalog if p["product_name"] == current_plan), None)
    current_tier = current["tier_level"] if current else 1
    candidates = [p for p in catalog if p["tier_level"] > current_tier]
    if not candidates:
        return None
    return min(candidates, key=lambda p: p["tier_level"])


def pick_addon_from_ticket_category(
    tickets: list[dict], catalog: list[dict], use_vector_search: bool = False, tenant_id: str = "default"
) -> dict | None:
    """
    Maps a support ticket to a relevant add-on product.

    Default (use_vector_search=False): keyword match against product name.
    Works well for a small, hand-curated catalog and needs zero extra
    dependencies -- this stays the default for exactly that reason.

    Optional (use_vector_search=True): semantic similarity via local
    embeddings (app.vector_engine), matching a ticket's actual subject text
    against every product's embedding. This is what scales past a catalog
    you can eyeball -- with hundreds or thousands of products you can't
    maintain a keyword list per category, and most product names won't
    literally contain the keyword.
    """
    if use_vector_search:
        from app.vector_engine import find_similar_products

        for ticket in tickets:
            if ticket["category"] not in ("security", "technical"):
                continue
            matches = find_similar_products(ticket["subject"], catalog, top_k=1, tenant_id=tenant_id)
            if matches:
                return matches[0]
        return None

    category_keywords = {
        "security": ["security", "defender", "compliance"],
        "technical": ["analytics", "storage", "performance"],
    }
    for ticket in tickets:
        keywords = category_keywords.get(ticket["category"], [])
        for product in catalog:
            if any(kw in product["product_name"].lower() for kw in keywords):
                return product
    return None


def rule_based_recommendation(
    customer: dict, usage_rows: list[dict], tickets: list[dict], catalog: list[dict],
    use_vector_search: bool = False, service_rows: list[dict] = None, tenant_id: str = "default",
) -> dict:
    """
    Deterministic recommendation logic — no LLM call, no DB access (matches
    the existing pattern: all data is passed in, nothing is fetched here,
    so this stays a pure function that's trivial to unit-test). Every
    branch is an explicit, auditable rule, and every rationale is built
    from a template referencing the actual computed numbers (never generic
    boilerplate).

    service_rows: optional per-service usage breakdown (app.db.get_service_usage
    output) for this customer, used only to name the top-driving service in
    the rationale. Safe to omit -- rationale just skips that detail.
    """
    trend = compute_usage_trend(usage_rows)
    storage = storage_pct_used(usage_rows)
    ticket_flag = has_relevant_ticket(tickets)
    renewal_days = days_to_renewal(customer["renewal_date"])

    # --- Churn risk estimation (simple deterministic rule, not a trained model) ---
    churn_risk, churn_reason = estimate_churn_risk(customer, usage_rows, tickets)

    # High churn risk customers never receive an upsell recommendation.
    if churn_risk == "high":
        return {
            "segment": "at-risk",
            "churn_risk": churn_risk,
            "churn_reason": churn_reason,
            "recommended_product": None,
            "recommendation_type": None,
            "rationale": "Recommendation suppressed due to high churn risk. Focus on retention.",
            "revenue_score": 0,
            "no_recommendation_reason_code": "high_churn_gate",
        }

    # --- Recommendation logic ---
    product = None
    recommendation_type = None
    rationale_parts = []
    score = 0

    if trend >= 15 and storage is not None and storage >= 80:
        product = pick_next_tier_product(customer["plan_tier"], catalog)
        recommendation_type = "upgrade"
        rationale_parts.append(f"usage grew {trend}% over the tracked period{_top_service_note(service_rows)}")
        rationale_parts.append(f"storage utilization reached {storage}%")
        score = 85
    elif ticket_flag:
        product = pick_addon_from_ticket_category(tickets, catalog, use_vector_search, tenant_id=tenant_id)
        recommendation_type = "cross-sell"
        matching_tickets = [t["subject"] for t in tickets if t["category"] in ("security", "technical")]
        rationale_parts.append(f"a recent support inquiry ({matching_tickets[0]}) suggests interest in this capability")
        score = 65
    elif renewal_days <= 90:
        recommendation_type = "renewal-upgrade"
        rationale_parts.append(f"renewal is in {renewal_days} days, a natural point to discuss expansion")
        score = 45
    elif trend >= 10:
        recommendation_type = "upgrade"
        product = pick_next_tier_product(customer["plan_tier"], catalog)
        rationale_parts.append(f"usage grew {trend}% over the tracked period{_top_service_note(service_rows)}")
        score = 55

    segment = "high-growth" if trend >= 15 else ("renewal-window" if renewal_days <= 90 else "stable-value")

    rationale = (
        f"Recommended because {', and '.join(rationale_parts)}."
        if rationale_parts and product
        else "No product change is clearly justified by current signals."
    )

    return {
        "segment": segment,
        "churn_risk": churn_risk,
        "churn_reason": churn_reason,
        "recommended_product": product["product_name"] if product else None,
        "recommendation_type": recommendation_type if product else None,
        "rationale": rationale,
        "revenue_score": score if product else 0,
        "no_recommendation_reason_code": None if product else "no_opportunity_found",
    }
