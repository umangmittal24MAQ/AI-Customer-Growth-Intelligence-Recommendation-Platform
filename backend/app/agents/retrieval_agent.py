from app.agents.clients import get_mini_client, wrap_agent, build_retrieval_fallback
from app.models import CandidateProducts
from app.vector_engine import find_similar_products
from app.prompts import RETRIEVAL_AGENT_PROMPT


def vector_search_tool(query_text: str, catalog: list, top_k: int = 3) -> list:
    return find_similar_products(query_text, catalog, top_k)


def build_retrieval_agent():
    client = get_mini_client()
    instructions = RETRIEVAL_AGENT_PROMPT
    agent = client.as_agent(
        name="catalog_retrieval_agent",
        instructions=instructions,
        response_model=CandidateProducts,
    )
    return wrap_agent(agent, build_retrieval_fallback, name="retrieval_agent")
