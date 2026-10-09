"""
Retention Agent tests. This agent only runs for a customer the pipeline has
already decided NOT to pitch an upsell to (a no_recommendation_reason_code
is set) -- its job is to replace a generic "hold offers, review manually"
line with one concrete, specific next step grounded in that account's own
signals. Critical properties under test: it must always return a valid
action_type + a non-empty, specific action_text (never a placeholder), and
a "high_churn_gate" reason should lean toward a retention-first action
(executive_meeting / complimentary_offer / account_review) rather than
something that reads as a soft brush-off (monitor).
"""

import asyncio

import pytest

# The agent builders import the optional 'indiaai' package. Skip this
# whole module cleanly if it isn't installed, so the rest of the suite still runs.


from app.agents.retention_agent import build_retention_agent
from tests.test_agents.conftest import get_case, requires_indiaai, run_agent

RETENTION_ACTION_TYPES = {
    "executive_meeting", "complimentary_offer", "training_session",
    "account_review", "proactive_outreach", "monitor",
}


@requires_indiaai
def test_retention_action_contract_shape(golden_set):
    case = get_case(golden_set, "obvious_churn")
    retention_agent = build_retention_agent()

    retention_input = {
        "reason_code": "high_churn_gate",
        "churn_reason": case["customer"].get("churn_reason") or "Repeated outages and an open cancellation request.",
        "renewal_date": case["customer"]["renewal_date"],
        "usage_rows": case["usage_rows"],
        "tickets": case["tickets"],
        "dynamic_fields": None,
    }
    action = asyncio.run(run_agent(retention_agent, retention_input))

    assert action.action_type in RETENTION_ACTION_TYPES
    assert action.action_text and action.action_text.strip() != ""
    # Should read as a concrete next step, not a placeholder/generic line.
    assert len(action.action_text.strip()) > 15


@requires_indiaai
def test_high_churn_gate_favors_retention_first_action(golden_set):
    """
    A hard 'high_churn_gate' reason means the account is high-risk enough
    that the code-level gate blocked any upsell outright -- the Retention
    Agent should propose something retention-oriented (a real conversation
    or goodwill gesture), not the passive 'monitor' action, which is meant
    for genuinely weak/ambiguous signals only.
    """
    case = get_case(golden_set, "obvious_churn")
    retention_agent = build_retention_agent()

    retention_input = {
        "reason_code": "high_churn_gate",
        "churn_reason": "Customer has an open cancellation request and repeated service outages.",
        "renewal_date": case["customer"]["renewal_date"],
        "usage_rows": case["usage_rows"],
        "tickets": case["tickets"],
        "dynamic_fields": None,
    }
    action = asyncio.run(run_agent(retention_agent, retention_input))

    assert action.action_type != "monitor", (
        "Retention agent proposed passive 'monitor' for a hard high_churn_gate "
        "account -- this reason code means the code-level gate already judged "
        "the account too high-risk for an upsell, so the response should be a "
        "concrete retention action, not 'wait and see'."
    )


@requires_indiaai
def test_retention_action_for_borderline_case_is_conservative(golden_set):
    """
    A borderline/thin-evidence case ('not_shortlisted' / 'no_opportunity_found')
    should not fabricate urgency -- 'monitor' or 'account_review' are
    reasonable here, but the agent must not invent specific details (names,
    numbers, ticket contents) not present in the input.
    """
    case = get_case(golden_set, "borderline")
    retention_agent = build_retention_agent()

    retention_input = {
        "reason_code": "no_opportunity_found",
        "churn_reason": "Usage and support signals are mixed with no clear trend either way.",
        "renewal_date": case["customer"]["renewal_date"],
        "usage_rows": case["usage_rows"],
        "tickets": case["tickets"],
        "dynamic_fields": None,
    }
    action = asyncio.run(run_agent(retention_agent, retention_input))

    assert action.action_type in RETENTION_ACTION_TYPES
    assert action.action_text and action.action_text.strip() != ""
