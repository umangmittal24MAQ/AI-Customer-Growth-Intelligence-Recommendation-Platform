from app.agents.clients import get_mini_client, wrap_agent, build_retention_fallback
from app.models import RetentionAction
from app.prompts import RETENTION_AGENT_PROMPT


def build_retention_agent():
    client = get_mini_client()
    instructions = RETENTION_AGENT_PROMPT
    agent = client.as_agent(
        name="retention_agent",
        instructions=instructions,
        response_model=RetentionAction,
    )
    return wrap_agent(agent, build_retention_fallback, name="retention_agent")
