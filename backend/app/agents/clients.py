"""IndiaAI-backed structured agents with explicit heuristic fallbacks.

Each model response is Pydantic-validated. No Azure or Microsoft Agent Framework
runtime is required. The existing workflow consumes `.run().value` unchanged.
"""
import json
from types import SimpleNamespace

from app.config import LLM_MODEL, LLM_TEMPERATURE
from app.indiaai_client import make_client
from app.llm_retry import completion_with_retry
from app.logging_config import get_logger
from app.models import CandidateProducts, CriticVerdict, Product, RecommendationDraft, RetentionAction, SignalVerdict

log = get_logger(__name__)


class _FallbackResponse:
    def __init__(self, value):
        self.value = value
        self.used_fallback = True


class _AgentWithFallback:
    def __init__(self, agent, fallback_factory, name="agent"):
        self._agent = agent
        self._fallback_factory = fallback_factory
        self._name = name

    async def run(self, message):
        try:
            return await self._agent.run(message)
        except Exception as exc:
            log.warning("IndiaAI agent '%s' failed (%s: %s); using explicit heuristic fallback.",
                        self._name, type(exc).__name__, exc)
            return _FallbackResponse(self._fallback_factory(message))


class IndiaAIStructuredAgent:
    def __init__(self, client, model: str, name: str, instructions: str, schema):
        self._client = client
        self._model = model
        self._name = name
        self._instructions = instructions
        self._schema = schema

    async def run(self, message):
        # JSON object mode is compatible with the diverse Pydantic contracts.
        # Pydantic validates required fields and Literal constraints before use.
        import os
        requested_tokens = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "2048"))
        generation_kwargs = {"max_tokens": requested_tokens}
        messages = [
            {"role": "system", "content": self._instructions +
             "\nReturn ONLY valid JSON matching this schema: " +
             json.dumps(self._schema.model_json_schema())},
            {"role": "user", "content": message if isinstance(message, str) else json.dumps(message, default=str)},
        ]
        for attempt in range(2):
            completion = await completion_with_retry(
                self._client, model=self._model, messages=messages,
                response_format={"type": "json_object"},
                temperature=LLM_TEMPERATURE, **generation_kwargs,
            )
            choices = getattr(completion, "choices", None) or []
            if not choices:
                raise ValueError(f"IndiaAI {self._name}: response has no choices")
            choice = choices[0]
            content = (getattr(choice.message, "content", None) or "").strip()
            if content:
                break
            finish_reason = getattr(choice, "finish_reason", "unknown")
            usage = getattr(completion, "usage", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            reasoning = getattr(choice.message, "reasoning_content", None)
            if reasoning is None:
                reasoning = (getattr(choice.message, "model_extra", None) or {}).get("reasoning_content")
            log.warning(
                "IndiaAI agent %s empty final content; finish_reason=%s completion_tokens=%s "
                "reasoning_present=%s max_tokens=%s attempt=%d/2",
                self._name, finish_reason, completion_tokens, bool(reasoning),
                generation_kwargs["max_tokens"], attempt + 1,
            )
            if attempt == 0:
                generation_kwargs["max_tokens"] = max(requested_tokens + 512, min(requested_tokens * 2, 4096))
                # If Qwen used the entire response on its reasoning, ask for
                # a concise answer on retry. Never treat thoughts as final JSON.
                messages[0] = dict(messages[0], content=messages[0]["content"] +
                                   "\nProduce the final JSON immediately; avoid extended deliberation.")
            else:
                raise ValueError(
                    f"IndiaAI {self._name} returned empty final content "
                    f"(finish_reason={finish_reason}, completion_tokens={completion_tokens})"
                )
        value = self._schema.model_validate_json(content)
        return SimpleNamespace(value=value, used_fallback=False)


class _IndiaAIAgentBuilder:
    def __init__(self, client, model):
        self._client = client
        self._model = model

    def as_agent(self, *, name, instructions, response_model):
        return IndiaAIStructuredAgent(self._client, self._model, name, instructions, response_model)


_mini_client = None
_strong_client = None


def get_mini_client():
    global _mini_client
    if _mini_client is None:
        _mini_client = _IndiaAIAgentBuilder(make_client(asynchronous=True), LLM_MODEL)
    return _mini_client


def get_strong_client():
    global _strong_client
    if _strong_client is None:
        _strong_client = _IndiaAIAgentBuilder(make_client(asynchronous=True), LLM_MODEL)
    return _strong_client


async def close_clients():
    global _mini_client, _strong_client
    closed = set()
    for builder in (_mini_client, _strong_client):
        if builder is not None and id(builder._client) not in closed:
            closed.add(id(builder._client))
            await builder._client.close()
    _mini_client = None
    _strong_client = None


def wrap_agent(agent, fallback_factory, name="agent"):
    return _AgentWithFallback(agent, fallback_factory, name=name)


def _parse_message(message):
    if isinstance(message, str):
        try:
            return json.loads(message)
        except json.JSONDecodeError:
            return {"raw": message}
    return message


def _flatten_text(message):
    payload = _parse_message(message)
    return (json.dumps(payload, default=str) if isinstance(payload, dict) else str(payload)).lower()


def build_signal_fallback(message):
    text = _flatten_text(message)
    churn_markers = ["cancel", "cancellation", "churn", "outage", "downtime", "service disruption", "issue"]
    growth_markers = ["growth", "expansion", "increase", "upsell", "high usage"]
    if any(marker in text for marker in churn_markers):
        return SignalVerdict(
            proceed=False,
            reason="Customer shows clear churn indicators; fallback heuristic stopped the recommendation.",
            urgency="high",
        )
    if any(marker in text for marker in growth_markers):
        return SignalVerdict(
            proceed=True,
            reason="Customer shows expansion signals and healthy usage trend.",
            urgency="low",
        )
    return SignalVerdict(
        proceed=True,
        reason="Fallback heuristic used because the live model was unavailable.",
        urgency="medium",
    )


def build_recommendation_fallback(message):
    return RecommendationDraft(
        product=None, segment="review_required", churn_risk="medium",
        churn_reason="IndiaAI did not return a validated recommendation.",
        rationale="No product generated; retry when provider is available.",
        revenue_score=0, confidence=0,
    )


def build_critic_fallback(message):
    return CriticVerdict(
        approved=False,
        revised_churn_risk=None,
        veto_reason="Critic model unavailable: recommendation needs manual verification.",
        churn_risk_reason="No validated second opinion was obtained.",
    )


def build_retention_fallback(message):
    payload = _parse_message(message)
    reason_code = payload.get("reason_code") if isinstance(payload, dict) else None
    passed_churn_reason = payload.get("churn_reason") if isinstance(payload, dict) else None
    text = _flatten_text(message)
    # Prefer whatever churn_reason was already passed in (itself agent-
    # generated upstream, e.g. by the Recommendation/Critic agent, or by
    # estimate_churn_risk's now customer-specific text) over a generic
    # sentence -- this fallback only fires when the live retention-agent
    # call itself errors, so it still shouldn't regress to a template if a
    # real per-customer reason is already sitting right there.
    reason_summary = passed_churn_reason or "No upsell was proposed for this account this cycle."
    if reason_code == "high_churn_gate":
        return RetentionAction(
            reason_summary=reason_summary,
            action_type="executive_meeting",
            action_text="Schedule a 1:1 renewal call with the account's decision-maker this week before proposing any new spend.",
            talking_point=None,
        )
    if any(marker in text for marker in ["outage", "downtime", "service disruption", "ticket"]):
        return RetentionAction(
            reason_summary=reason_summary,
            action_type="complimentary_offer",
            action_text="Offer a complimentary service credit or free training session to address recent support friction before the renewal conversation.",
            talking_point=None,
        )
    if reason_code in ("no_opportunity_found", "not_shortlisted"):
        return RetentionAction(
            reason_summary=reason_summary,
            action_type="proactive_outreach",
            action_text="Send a light-touch check-in to confirm the account is getting value, with no upsell attached this cycle.",
            talking_point=None,
        )
    return RetentionAction(
        reason_summary=reason_summary,
        action_type="account_review",
        action_text="Flag for a manual account review before deciding on next steps -- fallback heuristic used because the live model was unavailable.",
        talking_point=None,
    )


def build_retrieval_fallback(message):
    payload = _parse_message(message)
    catalog = payload.get("catalog") if isinstance(payload, dict) else None
    if isinstance(catalog, list) and catalog:
        products = []
        for item in catalog[:3]:
            if isinstance(item, dict):
                products.append(
                    {
                        "product_name": item.get("product_name") or item.get("name") or "Unknown product",
                        "price_per_seat": item.get("price_per_seat", 0),
                        "description": item.get("description"),
                    }
                )
        return CandidateProducts(products=[Product(**p) for p in products], method_used="keyword")
    return CandidateProducts(products=[], method_used="keyword")