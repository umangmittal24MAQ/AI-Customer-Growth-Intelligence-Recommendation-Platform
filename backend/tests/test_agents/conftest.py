"""
Shared fixtures for agent tests. These call the real IndiaAI agents
(no mocking) -- they're integration tests for the contract + business
invariants, not unit tests of prompt wording. They're skipped automatically
if IndiaAI credentials aren't configured, so the suite stays runnable in
CI/environments without keys (falls back to just the rule-based regression
suite + test_prefilter.py).
"""

import json
import os
from pathlib import Path

import pytest

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"

INDIAAI_CREDS_PRESENT = bool(os.environ.get("INDIAAI_API_KEY"))
requires_indiaai = pytest.mark.skipif(
    not INDIAAI_CREDS_PRESENT,
    reason="Live IndiaAI tests require INDIAAI_API_KEY; offline suite uses mocked provider tests.",
)


def to_message(payload: dict) -> str:
    """Matches app.agents.workflow._to_message -- agent.run() takes message
    text, not a raw dict, so every test serializes its payload the same way
    production code does."""
    return json.dumps(payload, default=str)


async def run_agent(agent, payload: dict):
    """Runs an agent with a dict payload and returns the parsed structured
    value (AgentResponse.value), matching workflow.py's calling convention."""
    response = await agent.run(to_message(payload))
    return response.value


@pytest.fixture(scope="session")
def golden_set():
    with open(GOLDEN_SET_PATH) as f:
        return json.load(f)


def get_case(golden_set, case_id):
    case = next(c for c in golden_set["cases"] if c["case_id"] == case_id)
    return case


def build_signal_request(case, tenant_profile):
    return {
        "customer_profile": case["customer"],
        "usage_rows": case["usage_rows"],
        "tickets": case["tickets"],
        "tenant_profile": tenant_profile,
    }
