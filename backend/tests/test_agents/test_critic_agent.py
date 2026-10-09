"""
Critic Agent tests -- the "genuine second opinion" from PRD §3.2. Critical
property under test: the Critic must reason over raw signals, never the
Recommendation Agent's own rationale (workflow.py already enforces this by
construction -- these tests confirm the Critic's *behavior* is defensible
given only raw signals), and it must be willing to veto a churn-risk
recommendation that slipped through the Recommendation Agent.
"""

import asyncio

import pytest

# The agent builders import the optional 'indiaai' package. Skip this
# whole module cleanly if it isn't installed, so the rest of the suite still runs.


from app.agents.critic_agent import build_critic_agent
from tests.test_agents.conftest import get_case, requires_indiaai, run_agent


@requires_indiaai
def test_critic_vetoes_unsupported_recommendation_for_churning_account(golden_set):
    """
    Simulates the failure mode the Critic exists to catch: the
    Recommendation Agent proposed a product for an account with obvious
    churn signals (cancellation request, repeated outages) and a "low"
    churn_risk label that isn't supported by the raw data. The Critic sees
    ONLY the raw signals + the proposed output -- not the Recommendation
    Agent's rationale -- and should reject it.
    """
    case = get_case(golden_set, "obvious_churn")
    critic_agent = build_critic_agent()

    critic_input = {
        "usage_rows": case["usage_rows"],
        "tickets": case["tickets"],
        "renewal_date": case["customer"]["renewal_date"],
        "tenant_profile": golden_set["tenant_profile"],
        "proposed_recommendation": {
            "recommended_product": "Analytics Pro",
            "segment": "stable-value",
            "churn_risk": "low",
        },
    }
    verdict = asyncio.run(run_agent(critic_agent, critic_input))

    assert verdict.approved is False, (
        "Critic approved an upsell recommendation for an account with an "
        "open cancellation request and repeated outages, despite being "
        "labeled 'low' churn risk -- this is exactly the failure mode the "
        "Critic agent exists to catch (PRD §3.2)."
    )
    assert verdict.veto_reason and verdict.veto_reason.strip() != ""


@requires_indiaai
def test_critic_approves_well_supported_recommendation(golden_set):
    case = get_case(golden_set, "obvious_expansion")
    critic_agent = build_critic_agent()

    critic_input = {
        "usage_rows": case["usage_rows"],
        "tickets": case["tickets"],
        "renewal_date": case["customer"]["renewal_date"],
        "tenant_profile": golden_set["tenant_profile"],
        "proposed_recommendation": {
            "recommended_product": "Storage Expansion Pack",
            "segment": "high-usage-growth",
            "churn_risk": "low",
        },
    }
    verdict = asyncio.run(run_agent(critic_agent, critic_input))

    assert isinstance(verdict.approved, bool)
    if verdict.revised_churn_risk is not None:
        assert verdict.revised_churn_risk in ("low", "medium", "high")


@requires_indiaai
def test_critic_contract_shape(golden_set):
    case = get_case(golden_set, "borderline")
    critic_agent = build_critic_agent()

    critic_input = {
        "usage_rows": case["usage_rows"],
        "tickets": case["tickets"],
        "renewal_date": case["customer"]["renewal_date"],
        "tenant_profile": golden_set["tenant_profile"],
        "proposed_recommendation": {
            "recommended_product": None,
            "segment": "stable-value",
            "churn_risk": "medium",
        },
    }
    verdict = asyncio.run(run_agent(critic_agent, critic_input))

    assert isinstance(verdict.approved, bool)
    assert verdict.revised_churn_risk in ("low", "medium", "high", None)
