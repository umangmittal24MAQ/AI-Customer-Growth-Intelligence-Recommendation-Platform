from app.agents.clients import get_mini_client, wrap_agent, build_signal_fallback
from app.logging_config import get_logger
from app.models import SignalVerdict
from app.prefilter import passes_prefilter
from app.prompts import SIGNAL_AGENT_PROMPT

log = get_logger(__name__)


def passes_prefilter_tool(customer: dict, usage_rows: list, tickets: list, tenant_profile: dict) -> bool:
    """Local deterministic prefilter helper (not called through IndiaAI tool use).

    The production pipeline applies passes_prefilter directly to original rows,
    avoiding having an LLM reconstruct tool arguments from loosely typed data.
    """
    try:
        return passes_prefilter(customer, usage_rows, tickets, tenant_profile)
    except Exception:
        log.exception(
            "passes_prefilter_tool raised for customer_id=%s -- this may be "
            "a genuine data issue OR the model malformed the tool-call "
            "arguments when reconstructing them; see traceback above.",
            customer.get("customer_id", "?"),
        )
        raise


def build_signal_agent():
    client = get_mini_client()
    instructions = SIGNAL_AGENT_PROMPT
    agent = client.as_agent(
        name="signal_agent",
        instructions=instructions,
        response_model=SignalVerdict,
    )
    return wrap_agent(agent, build_signal_fallback, name="signal_agent")
