"""
Recommendation Agent tests -- the core reasoning step. Business invariant
under test (per PRD FR2 / prompts/agents/recommendation_agent.txt): if the
agent itself assesses churn_risk as "high", it must not also recommend a
product. This is checked independently of the Critic and the code-level
gate (workflow.py enforces the gate separately) -- this test is specifically
about whether the Recommendation agent's OWN output is internally
consistent, since that's the one rule the PRD says shouldn't rely on a
single model call alone.
"""

import asyncio

import pytest

# The agent builders import the optional 'indiaai' package. Skip this
# whole module cleanly if it isn't installed, so the rest of the suite still runs.


from app.agents.recommendation_agent import build_recommendation_agent
from app.agents.retrieval_agent import build_retrieval_agent
from app.agents.signal_agent import build_signal_agent
from tests.test_agents.conftest import build_signal_request, get_case, requires_indiaai, run_agent


def _run_signal_and_retrieval(case, tenant_profile, catalog):
    signal_agent = build_signal_agent()
    request = build_signal_request(case, tenant_profile)
    signal_verdict = asyncio.run(run_agent(signal_agent, request))

    retrieval_agent = build_retrieval_agent()
    retrieval_input = {**request, "signal_verdict": signal_verdict.dict(), "catalog": catalog}
    candidates = asyncio.run(run_agent(retrieval_agent, retrieval_input))
    return request, signal_verdict, candidates


@requires_indiaai
def test_expansion_customer_gets_grounded_recommendation(golden_set):
    case = get_case(golden_set, "obvious_expansion")
    catalog = golden_set["catalog"]
    request, signal_verdict, candidates = _run_signal_and_retrieval(
        case, golden_set["tenant_profile"], catalog
    )

    rec_agent = build_recommendation_agent()
    rec_input = {
        **request,
        "signal_verdict": signal_verdict.dict(),
        "candidate_products": [p.dict() for p in candidates.products],
    }
    recommendation = asyncio.run(run_agent(rec_agent, rec_input))

    # Contract-level checks
    assert recommendation.churn_risk in ("low", "medium", "high")
    assert 0 <= recommendation.revenue_score <= 100
    assert recommendation.rationale.strip() != ""

    # Never invent a product outside the catalog
    catalog_names = {p["product_name"] for p in catalog}
    if recommendation.product:
        assert recommendation.product in catalog_names

    # The core internal-consistency rule
    if recommendation.churn_risk == "high":
        assert recommendation.product is None


@requires_indiaai
def test_churn_customer_never_gets_product_from_recommendation_agent(golden_set):
    case = get_case(golden_set, "obvious_churn")
    catalog = golden_set["catalog"]
    request, signal_verdict, candidates = _run_signal_and_retrieval(
        case, golden_set["tenant_profile"], catalog
    )

    rec_agent = build_recommendation_agent()
    rec_input = {
        **request,
        "signal_verdict": signal_verdict.dict(),
        "candidate_products": [p.dict() for p in candidates.products],
    }
    recommendation = asyncio.run(run_agent(rec_agent, rec_input))

    if recommendation.churn_risk == "high":
        assert recommendation.product is None, (
            "Recommendation agent flagged high churn risk but still "
            "returned a product -- violates the internal consistency "
            "rule in prompts/agents/recommendation_agent.txt, which the "
            "Critic + code-gate exist to catch as a second/third line of "
            "defense, but shouldn't happen at this layer either."
        )
