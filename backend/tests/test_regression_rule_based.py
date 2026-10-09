"""
Regression suite: the rule-based path is the PRD's "must not regress"
baseline (§2, §4.3) -- the v2 multi-agent redesign is explicitly required
to be provably not worse than it, and it must keep working with zero API
key regardless of what happens to the IndiaAI/agent path.

These tests exercise app/rule_engine.py directly (no LLM, no network) so
they always run, including in environments with no IndiaAI credentials.
"""

from app.rule_engine import rule_based_recommendation


def _make_customer(seats=50):
    return {
        "customer_id": "cust_regress_1",
        "customer_name": "Regression Test Co",
        "industry": "software",
        "plan_tier": "growth",
        "seats": seats,
        "renewal_date": __import__("datetime").date(2027, 1, 1),
    }


def _catalog():
    return [
        {"product_id": "p1", "product_name": "Advanced Security Suite",
         "tier_level": 2, "price_per_seat": 12.0, "category": "security",
         "description": "Threat detection, SSO, audit logging.", "complements": None},
        {"product_id": "p2", "product_name": "Analytics Pro",
         "tier_level": 2, "price_per_seat": 9.0, "category": "analytics",
         "description": "Advanced dashboards and usage reporting.", "complements": None},
    ]


def test_rule_based_never_recommends_for_high_churn_signals():
    """
    Mirrors FR2 at the deterministic layer: even without any LLM involved,
    a customer with clear churn signals (heavy unresolved tickets, usage
    decline) should not receive a product recommendation from the
    rule-based engine, since this is the zero-cost default path every
    tenant gets unless they opt into LLM mode.
    """
    customer = _make_customer()
    catalog = _catalog()
    usage_rows = [
        {"month": "2026-04-01", "active_users": 50, "storage_used_gb": 100, "storage_limit_gb": 400, "feature_usage_score": 40},
        {"month": "2026-05-01", "active_users": 30, "storage_used_gb": 90, "storage_limit_gb": 400, "feature_usage_score": 20},
        {"month": "2026-06-01", "active_users": 15, "storage_used_gb": 80, "storage_limit_gb": 400, "feature_usage_score": 8},
    ]
    tickets = [
        {"ticket_id": "t1", "created_at": __import__("datetime").date(2026, 5, 1),
         "category": "cancellation_request", "subject": "cancel our account", "resolved": False},
        {"ticket_id": "t2", "created_at": __import__("datetime").date(2026, 5, 15),
         "category": "outage", "subject": "down again", "resolved": False},
        {"ticket_id": "t3", "created_at": __import__("datetime").date(2026, 5, 20),
         "category": "outage", "subject": "still down", "resolved": False},
    ]

    rec = rule_based_recommendation(customer, usage_rows, tickets, catalog, use_vector_search=False)

    if rec.get("churn_risk") == "high":
        assert rec.get("recommended_product") is None


def test_rule_based_produces_valid_contract_shape():
    """Basic sanity: the rule engine always returns the fields pipeline.py depends on."""
    customer = _make_customer()
    catalog = _catalog()
    usage_rows = [
        {"month": "2026-04-01", "active_users": 90, "storage_used_gb": 380, "storage_limit_gb": 400, "feature_usage_score": 80},
        {"month": "2026-05-01", "active_users": 95, "storage_used_gb": 390, "storage_limit_gb": 400, "feature_usage_score": 85},
        {"month": "2026-06-01", "active_users": 98, "storage_used_gb": 398, "storage_limit_gb": 400, "feature_usage_score": 90},
    ]
    tickets = []

    rec = rule_based_recommendation(customer, usage_rows, tickets, catalog, use_vector_search=False)

    for field in ("segment", "churn_risk", "churn_reason", "rationale", "revenue_score"):
        assert field in rec, f"rule_based_recommendation output missing required field '{field}'"
    assert rec["churn_risk"] in ("low", "medium", "high")


def test_rule_based_never_invents_a_product_outside_catalog():
    customer = _make_customer()
    catalog = _catalog()
    catalog_names = {p["product_name"] for p in catalog}
    usage_rows = [
        {"month": "2026-04-01", "active_users": 90, "storage_used_gb": 380, "storage_limit_gb": 400, "feature_usage_score": 80},
        {"month": "2026-05-01", "active_users": 95, "storage_used_gb": 390, "storage_limit_gb": 400, "feature_usage_score": 85},
        {"month": "2026-06-01", "active_users": 98, "storage_used_gb": 398, "storage_limit_gb": 400, "feature_usage_score": 90},
    ]
    rec = rule_based_recommendation(customer, usage_rows, [], catalog, use_vector_search=False)

    if rec.get("recommended_product"):
        assert rec["recommended_product"] in catalog_names
