"""
Signal Agent tests -- FR: this agent must be conservative about what
proceeds to the rest of the pipeline, and its `proceed`/`reason` must be
grounded in the data it was given (checked loosely here; exact wording
isn't asserted since LLM phrasing varies run to run).
"""

import asyncio

import pytest

# The agent builders import the optional 'indiaai' package. Skip this
# whole module cleanly if it isn't installed, so the rest of the suite (rule
# based + prefilter + client tests) still runs.


from app.agents.signal_agent import build_signal_agent
from tests.test_agents.conftest import build_signal_request, get_case, requires_indiaai, run_agent


@requires_indiaai
def test_obvious_expansion_customer_proceeds(golden_set):
    case = get_case(golden_set, "obvious_expansion")
    request = build_signal_request(case, golden_set["tenant_profile"])
    agent = build_signal_agent()

    verdict = asyncio.run(run_agent(agent, request))

    assert verdict.proceed is True, (
        f"Expected a high-usage-growth, low-ticket customer to proceed, "
        f"got proceed=False, reason={verdict.reason!r}"
    )
    assert verdict.urgency in ("low", "medium", "high")
    assert verdict.reason.strip() != ""


@requires_indiaai
def test_obvious_churn_customer_is_flagged_or_stopped(golden_set):
    """
    The Signal agent isn't required to stop a churning account (that's the
    Recommendation/Critic/code-gate's job downstream), but if it does let
    the account proceed, it must at least flag high urgency rather than
    treating a customer that's actively requesting cancellation as routine.
    """
    case = get_case(golden_set, "obvious_churn")
    request = build_signal_request(case, golden_set["tenant_profile"])
    agent = build_signal_agent()

    verdict = asyncio.run(run_agent(agent, request))

    if verdict.proceed:
        assert verdict.urgency == "high", (
            "A customer with an open cancellation request and repeated "
            "outages should be marked high urgency if the Signal agent "
            "lets the pipeline continue for them at all."
        )


@requires_indiaai
def test_borderline_customer_returns_valid_contract(golden_set):
    case = get_case(golden_set, "borderline")
    request = build_signal_request(case, golden_set["tenant_profile"])
    agent = build_signal_agent()

    verdict = asyncio.run(run_agent(agent, request))

    assert isinstance(verdict.proceed, bool)
    assert verdict.urgency in ("low", "medium", "high")
    assert verdict.reason.strip() != ""
