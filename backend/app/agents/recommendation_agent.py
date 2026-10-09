from app.agents.clients import get_strong_client, wrap_agent, build_recommendation_fallback
from app.models import RecommendationDraft
from app.prompts import RECOMMENDATION_AGENT_PROMPT


def build_recommendation_agent():
    client = get_strong_client()
    instructions = RECOMMENDATION_AGENT_PROMPT
    agent = client.as_agent(
        name="recommendation_agent",
        instructions=instructions,
        response_model=RecommendationDraft,
    )
    return wrap_agent(agent, build_recommendation_fallback, name="recommendation_agent")
