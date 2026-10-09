from app.agents.clients import get_mini_client, wrap_agent, build_critic_fallback
from app.models import CriticVerdict
from app.prompts import CRITIC_AGENT_PROMPT


def build_critic_agent():
    client = get_mini_client()
    instructions = CRITIC_AGENT_PROMPT
    agent = client.as_agent(
        name="churn_critic_agent",
        instructions=instructions,
        response_model=CriticVerdict,
    )
    return wrap_agent(agent, build_critic_fallback, name="critic_agent")
