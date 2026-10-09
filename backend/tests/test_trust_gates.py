"""Tests for recommendation invariants (no provider key/network required)."""
import asyncio
import json
from types import SimpleNamespace
from datetime import date
import pytest
from app import db

@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "gate.db"))
    db.init_db()


from app.trust import eligible_catalog, evidence_supports_expansion, compact_signals
from app.models import RecommendationDraft, CriticVerdict
from app.agents.clients import build_critic_fallback, build_recommendation_fallback
from app.agents.workflow import run_customer
from app.llm_retry import retry_after_seconds

CATALOG = [
    {"product_name": "Starter Swim", "category": "swim", "tier_level": 1, "price_per_seat": 8},
    {"product_name": "Advanced Swim", "category": "swim", "tier_level": 2, "price_per_seat": 20},
    {"product_name": "Elite Swim", "category": "swim", "tier_level": 3, "price_per_seat": 40},
    {"product_name": "Badminton Racket", "category": "badminton", "tier_level": 2, "price_per_seat": 20},
]
CUSTOMER = {"customer_id": "DEMO-001", "customer_name": "Swimming Test Store", "plan_tier": "Starter Swim",
            "renewal_date": date(2027, 1, 5), "seats": 50}
SIGNALS = {"usage_rows": [
    {"feature_usage_score": 40, "month": "2026-07-01"},
    {"feature_usage_score": 65, "month": "2026-08-01"},
    {"feature_usage_score": 80, "month": "2026-09-01"},
], "tickets": [], "customer_profile": CUSTOMER}


def test_catalog_stays_in_product_family_and_next_tier():
    rows, reason = eligible_catalog(CATALOG, CUSTOMER, SIGNALS)
    assert reason == "eligible_filtered"
    assert [p['product_name'] for p in rows] == ['Advanced Swim']
    assert 'Badminton Racket' not in [p['product_name'] for p in rows]


def test_unknown_plan_abstains():
    rows, reason = eligible_catalog(CATALOG, {**CUSTOMER, 'plan_tier': '???'}, SIGNALS)
    assert not rows and reason == 'unknown_current_product'


def test_no_invented_growth_from_steady_metrics():
    assert evidence_supports_expansion(SIGNALS)
    assert not evidence_supports_expansion({"usage_rows": [{"feature_usage_score": 50},
        {"feature_usage_score": 51}], "tickets": []})


def test_compact_prompts_use_four_latest_months():
    out = compact_signals({**SIGNALS, "usage_rows": [{"feature_usage_score": x} for x in range(24)],
                           "datasets": [{"dataset_label": "a", "rows": list(range(100))}]})
    assert len(out['usage_rows']) == 4
    assert len(out['datasets'][0]['rows']) == 2


def test_critic_fallback_always_rejects():
    verdict = build_critic_fallback('{}')
    assert verdict.approved is False
    assert build_recommendation_fallback('{}').product is None


class FakeAgent:
    def __init__(self, value, fallback=False):
        self.value, self.fallback, self.calls = value, fallback, 0
    async def run(self, message):
        self.calls += 1
        return SimpleNamespace(value=self.value, used_fallback=self.fallback)


def agents_for(product='Advanced Swim', approve=True, critic_fallback=False, recommendation_fallback=False):
    rec = FakeAgent(RecommendationDraft(product=product, segment='growth', churn_risk='low',
        churn_reason='stable', rationale='Growing usage (40 to 80).', revenue_score=80, confidence=.82),
        recommendation_fallback)
    critic = FakeAgent(CriticVerdict(approved=approve, revised_churn_risk='low',
        veto_reason=None if approve else 'Evidence does not support product'), critic_fallback)
    return {"recommendation_agent": rec, "critic_agent": critic}, rec, critic


def evaluate(agents, signals=None):
    return asyncio.run(run_customer(signals or SIGNALS, CUSTOMER, CATALOG, agents, tenant_id='test-tenant'))


def test_critic_veto_is_final_no_revenue():
    agents, _, _ = agents_for(approve=False)
    result = evaluate(agents)
    assert result['recommended_product'] is None
    assert result['estimated_deal_value'] == 0
    assert result['revenue_score'] == 0
    assert result['confidence'] == 0
    assert result['no_recommendation_reason_code'] == 'critic_vetoed'


def test_model_unavailable_never_qualifies():
    agents, _, critic = agents_for(critic_fallback=True)
    result = evaluate(agents)
    assert result['recommended_product'] is None
    assert 'critic' in result['agent_trace']['fallbacks_used']
    assert result['agent_trace']['decision_status'] == 'review_required'


def test_invalid_product_does_not_reach_critic():
    agents, _, critic = agents_for(product='Badminton Racket')
    result = evaluate(agents)
    assert result['recommended_product'] is None
    assert result['no_recommendation_reason_code'] == 'invalid_catalog_product'
    assert critic.calls == 0


def test_missing_growth_skips_all_llm_calls():
    agents, rec, critic = agents_for()
    result = evaluate(agents, {"usage_rows": [{"feature_usage_score": 50}, {"feature_usage_score": 51}],
        "tickets": [], "customer_profile": CUSTOMER})
    assert result['recommended_product'] is None
    assert rec.calls == critic.calls == 0


def test_rate_limit_error_parser():
    class RateLimit:
        def __str__(self):
            return 'Please try again in 4.14s'
    assert retry_after_seconds(RateLimit(), 0) >= 4.14
