import json
from datetime import datetime

from app.agents.signal_agent import build_signal_agent
from app.agents.recommendation_agent import build_recommendation_agent
from app.agents.critic_agent import build_critic_agent
from app.agents.retention_agent import build_retention_agent
from app.agents.deal_value_agent import compute_deal_value
from app.prefilter import estimate_churn_risk
from app.logging_config import get_logger
from app.config import LLM_MODEL
from app.models import SignalVerdict, CandidateProducts, RecommendationDraft, CriticVerdict, Product, RetentionAction
from app.trust import eligible_catalog, source_evidence, compact_signals, evidence_supports_expansion
from app.agents.clients import build_retention_fallback
from types import SimpleNamespace
from app.prefilter import estimate_churn_risk
from app.vector_engine import find_similar_products
# Catalog pitch selection lives in the dependency-free app.agents.pitch module
# so the batch pipeline can reuse it without importing the agent stack. Aliased
# to the private names this module has always used at the call sites below.
from app.agents.pitch import (
    classify_rec_type as _classify_rec_type,
    pitch_from_catalog as _pitch_from_catalog,
)
from app.agents.confidence import (
    compute_confidence,
    compute_data_completeness,
    compute_retrieval_fit,
)

log = get_logger(__name__)


def _used_fallback(response) -> bool:
    """True if this response came from the heuristic fallback, not a live model."""
    return getattr(response, "used_fallback", False)


def _to_message(payload: dict) -> str:
    """
    agent.run() takes message text/content, not an arbitrary Python dict --
    the agent contracts here are all "read this JSON context, return this
    structured schema", so we serialize the payload as JSON text for the
    model to read. default=str handles date/datetime objects that show up
    in customer/usage_row/ticket dicts pulled straight from the DB layer.
    """
    return json.dumps(payload, default=str)


def build_agents():
    """Build the three agents actually used per customer, once. Reuse the
    returned dict across every customer in a batch run -- rebuilding these
    per customer creates a new IndiaAI client (and underlying
    httpx.AsyncClient connection pool) on every call, which then leaks
    because nothing closes it.

    No retrieval agent here: catalog narrowing now calls find_similar_products
    directly (see run_customer) instead of routing through an LLM-wrapped
    tool call, so there's no retrieval client to build or leak."""
    log.info("Building two AI agents: recommendation + independent critic.")
    return {
        "recommendation_agent": build_recommendation_agent(),
        "critic_agent": build_critic_agent(),
    }


async def _run_retention_agent(retention_agent, customer, reason_code, churn_reason, customer_signal_request, fallbacks_used):
    """Generates a concrete, specific "what to do instead" action for a
    customer the pipeline decided not to pitch this cycle. Only called when
    a no_recommendation_reason_code is actually set -- never on a confident
    upsell path. Returns a dict (RetentionAction.model_dump()) or None if the
    reason_code somehow wasn't set."""
    if not reason_code:
        return None
    retention_input = {
        "reason_code": reason_code,
        "churn_reason": churn_reason,
        "renewal_date": customer.get("renewal_date"),
        "usage_rows": customer_signal_request.get("usage_rows"),
        "tickets": compact_signals(customer_signal_request).get("tickets"),
        "dynamic_fields": customer_signal_request.get("dynamic_fields"),
    }
    response = await retention_agent.run(_to_message(retention_input))
    action: RetentionAction = response.value
    if _used_fallback(response):
        fallbacks_used.append("retention")
    return action.model_dump()


async def run_customer(customer_signal_request: dict, customer: dict, catalog: list[dict], agents: dict, tenant_id: str = "default") -> dict:
    signal_agent = agents.get("signal_agent")
    recommendation_agent = agents["recommendation_agent"]
    critic_agent = agents["critic_agent"]

    customer_id = customer["customer_id"]
    fallbacks_used = []
    log.info("[%s] Starting agent pipeline for '%s'.", customer_id, customer.get("customer_name", "?"))

    # Step 1: deterministic risk screening. Avoid spending an AI call deciding
    # whether obvious missing data/high churn needs manual review.
    det_risk, det_reason = estimate_churn_risk(
        customer, customer_signal_request.get("usage_rows") or [], customer_signal_request.get("tickets") or []
    )
    has_supporting_data = bool(customer_signal_request.get("usage_rows") or
                               customer_signal_request.get("tickets") or
                               customer_signal_request.get("dynamic_fields"))
    reason_code = ("high_churn_gate" if det_risk == "high" else
                   "insufficient_evidence" if not has_supporting_data else
                   "no_expansion_signal" if not evidence_supports_expansion(customer_signal_request) else None)
    evidence = source_evidence(customer, customer_signal_request)
    if reason_code:
        action = build_retention_fallback(_to_message({"reason_code": reason_code, "churn_reason": det_reason})).model_dump()
        log.info("[%s] Abstained at deterministic screening: %s", customer_id, reason_code)
        return {
            "customer_id": customer_id, "customer_name": customer.get("customer_name", customer_id),
            "recommended_product": None, "recommendation_type": None, "is_low_confidence_pitch": False,
            "no_recommendation_reason_code": reason_code, "retention_action": action,
            "churn_risk": det_risk, "churn_reason": det_reason, "segment": "review_required",
            "rationale": det_reason if reason_code == "high_churn_gate" else
                "No credible expansion trigger was found in the current account data.",
            "revenue_score": 0, "confidence": 0, "estimated_deal_value": 0,
            "renewal_date": str(customer.get("renewal_date") or ""), "generated_at": datetime.utcnow().isoformat(),
            "agent_trace": {"agents_run": ["deterministic_screen"], "outcome": "review_required",
                            "decision_status": "review_required", "reason_code": reason_code,
                            "evidence": evidence, "fallbacks_used": []},
        }
    signal_result = SignalVerdict(proceed=True, urgency="medium", reason="Eligible for product evaluation after deterministic risk screening.")

    # Step 2: business-eligible retrieval. NEVER hand all 52 products to an LLM.
    eligible, retrieval_method = eligible_catalog(catalog, customer, customer_signal_request)
    if not eligible:
        return {
            "customer_id": customer_id, "customer_name": customer.get("customer_name", customer_id),
            "recommended_product": None, "recommendation_type": None, "is_low_confidence_pitch": False,
            "no_recommendation_reason_code": retrieval_method, "retention_action": build_retention_fallback(
                _to_message({"reason_code": "no_opportunity_found", "churn_reason": retrieval_method})).model_dump(),
            "churn_risk": det_risk, "churn_reason": det_reason, "segment": "not_eligible",
            "rationale": "Catalog contains no evidence-supported upgrade or cross-sell for this account.",
            "revenue_score": 0, "confidence": 0, "estimated_deal_value": 0,
            "renewal_date": str(customer.get("renewal_date") or ""), "generated_at": datetime.utcnow().isoformat(),
            "agent_trace": {"agents_run": ["deterministic_screen", "eligible_catalog"],
                            "outcome": "no_opportunity", "decision_status": "no_opportunity",
                            "reason_code": retrieval_method, "evidence": evidence,
                            "candidate_count": 0, "fallbacks_used": []},
        }
    candidates = CandidateProducts(products=[Product(product_name=x["product_name"],
        price_per_seat=float(x.get("price_per_seat") or 0), description=x.get("description"))
        for x in eligible], method_used="keyword")
    log.info("[%s] Eligible catalog: %d/%d products", customer_id, len(eligible), len(catalog))

    # Step 3 - Recommendation Agent: the core reasoning step
    recommendation_input = {
        **compact_signals(customer_signal_request),
        "signal_verdict": signal_result.model_dump(),
        "candidate_products": [p.model_dump() for p in candidates.products],
    }
    recommendation_response = await recommendation_agent.run(_to_message(recommendation_input))
    draft: RecommendationDraft = recommendation_response.value
    if _used_fallback(recommendation_response):
        fallbacks_used.append("recommendation")
    log.info(
        "[%s] Recommendation agent: product=%s segment=%s churn=%s score=%s",
        customer_id, draft.product, draft.segment, draft.churn_risk, draft.revenue_score,
    )

    # A failed IndiaAI call must NEVER manufacture an eligible revenue lead.
    if _used_fallback(recommendation_response):
        draft.product = None
    eligible_names = {item["product_name"].casefold(): item["product_name"] for item in eligible}
    if draft.product and draft.product.casefold() not in eligible_names:
        log.warning("[%s] LLM proposed out-of-eligibility catalog product: %s", customer_id, draft.product)
        draft.product = None
        invalid_product = True
    else:
        invalid_product = False
    if draft.product:
        draft.product = eligible_names[draft.product.casefold()]

    # Step 4 - Churn-Risk Critic Agent: independent second opinion.
    # Deliberately pass ONLY raw signals + the recommendation's final output --
    # never the Recommendation Agent's own reasoning/rationale text.
    # dynamic_fields / ticket_dynamic_fields / usage_dynamic_fields are all
    # included here as raw evidence (same category as usage_rows/tickets),
    # not reasoning -- so the critic can weigh a tenant-specific signal like
    # NPS, a ticket-level Priority_Score, or a discovered usage metric
    # without seeing why the Recommendation agent thinks it matters. Prior
    # to this, only `dynamic_fields` (customer-level) was passed through,
    # so the critic never saw ticket- or usage-level discovered columns at all.
    critic_input = {
        **compact_signals(customer_signal_request),
        "renewal_date": customer.get("renewal_date"),
        "proposed_recommendation": {
            "recommended_product": draft.product,
            "segment": draft.segment,
            "churn_risk": draft.churn_risk,
        },
    }
    if draft.product:
        critic_response = await critic_agent.run(_to_message(critic_input))
        critic: CriticVerdict = critic_response.value
        if _used_fallback(critic_response):
            fallbacks_used.append("critic")
            critic = CriticVerdict(approved=False, revised_churn_risk=det_risk,
                veto_reason="Critic model unavailable; human verification required.")
    else:
        critic = CriticVerdict(approved=False, revised_churn_risk=det_risk,
            veto_reason="No verified, eligible recommendation was produced.")
    log.info(
        "[%s] Critic agent: approved=%s revised_churn=%s veto=%s",
        customer_id, critic.approved, critic.revised_churn_risk, critic.veto_reason,
    )

    # Merge critic verdict onto the recommendation draft, translating the
    # slim agent contract (`product`) into the DB-shaped field name
    # (`recommended_product`) expected by db.log_recommendation / models.Recommendation.
    final = {
        "segment": draft.segment,
        "churn_risk": draft.churn_risk,
        "churn_reason": draft.churn_reason,
        "recommended_product": draft.product,
        "recommendation_type": None,
        "rationale": draft.rationale,
        "revenue_score": draft.revenue_score,
        # Distinguishes *why* recommended_product may be null, since "no
        # opportunity found by the Recommendation agent," "Critic vetoed an
        # actual draft," and "high churn risk code-gate," were previously
        # all indistinguishable from each other (and from a Signal-agent
        # rejection, see "signal_rejected" above) once they reached the
        # API response -- null is null with no way to tell which one fired.
        "no_recommendation_reason_code": None if draft.product is not None else ("invalid_catalog_product" if invalid_product else "unverified_model_output" if fallbacks_used else "no_opportunity_found"),
    }
    
    # Enforce deterministic churn risk:
    det_risk, det_reason = estimate_churn_risk(
        customer,
        customer_signal_request.get("usage_rows") or [],
        customer_signal_request.get("tickets") or [],
    )
    final["churn_risk"] = det_risk
    
    # Do not let critic override the deterministic churn risk
    # (Previously: if critic.revised_churn_risk is not None: final["churn_risk"] = critic.revised_churn_risk)

    # Prefer the critic's product-agnostic churn reasoning over the
    # Recommendation agent's own churn_reason whenever the critic ran and
    # supplied one -- it's the more independent, second-opinion read of
    # the account, and (unlike veto_reason) it's guaranteed not to name a
    # product that might get swapped out for a fallback pitch below.
    if critic.churn_risk_reason:
        final["churn_reason"] = critic.churn_risk_reason
    if not critic.approved and final["recommended_product"]:
        log.info("[%s] Critic VETOED the recommendation -- product removed.", customer_id)
        final["recommended_product"] = None
        final["no_recommendation_reason_code"] = "critic_vetoed"
        # NOTE: deliberately NOT overwriting churn_reason with
        # critic.veto_reason here anymore -- veto_reason is about the
        # (now-discarded) proposed product specifically and may name it,
        # which reads as incoherent once a different, unrelated product
        # gets pitched instead (see the fallback-pitch block below).
        # veto_reason is preserved in agent_trace for debugging instead.

    # (Gate removed: we now allow recommending optimization/analytics products for high-risk accounts)

    # Step 4.5: deterministic next action; no extra IndiaAI calls for rejected leads.
    final["retention_action"] = None
    if final.get("no_recommendation_reason_code"):
        final["retention_action"] = build_retention_fallback(_to_message({
            "reason_code": final["no_recommendation_reason_code"],
            "churn_reason": final.get("churn_reason") or critic.veto_reason,
        })).model_dump()
    final["is_low_confidence_pitch"] = False
    if final["recommended_product"] is None:
        final["confidence"] = 0
        final["revenue_score"] = 0
        final["rationale"] = critic.veto_reason or final["rationale"]

    # Label the *kind* of confident recommendation (upgrade vs cross-sell)
    # from the catalog tiers, so the analysis view shows which move it is.
    # The low-confidence pitch path above already sets its own type, so only
    # fill this when a product exists and the type is still unset.
    if final["recommended_product"] and final.get("recommendation_type") is None:
        final["recommendation_type"] = _classify_rec_type(
            catalog, customer.get("plan_tier"), final["recommended_product"]
        )

    # Confidence -- how sure we are this recommendation is RIGHT for this
    # customer (distinct from revenue_score / deal size). Blends the agent's
    # own self-assessment with how complete this customer's evidence was and
    # how well the product fits their current tier, then penalizes heuristic
    # fallbacks and lets the critic moderate it down. A low-confidence catalog
    # pitch (filled in above for a veto / high-churn gate / no-opportunity) is
    # capped low; a product-less outcome is 0. See app/agents/confidence.py.
    completeness = compute_data_completeness(
        customer,
        customer_signal_request.get("usage_rows") or [],
        customer_signal_request.get("tickets") or [],
        customer_signal_request,
        tenant_id,
    )
    final["confidence"] = compute_confidence(
        llm_confidence=draft.confidence,
        data_completeness=completeness,
        retrieval_fit=compute_retrieval_fit(
            catalog, customer.get("plan_tier"), final["recommended_product"], candidates.method_used,
        ),
        used_fallbacks=fallbacks_used,
        is_low_confidence_pitch=final["is_low_confidence_pitch"],
        has_product=bool(final["recommended_product"]),
        critic_penalty=critic.confidence_penalty,
    )

    # Step 5 - Deal Value (plain math, not an LLM agent)
    deal_value = compute_deal_value(final, customer, catalog)
    final["estimated_deal_value"] = deal_value.estimated_value
    log.info(
        "[%s] Deal value: $%s anomaly=%s",
        customer_id, deal_value.estimated_value, deal_value.anomaly_flag,
    )

    # Required fields the Recommendation Agent doesn't produce - fill from customer record
    final["customer_id"] = customer["customer_id"]
    final["customer_name"] = customer["customer_name"]
    final["renewal_date"] = customer["renewal_date"].isoformat() if hasattr(customer["renewal_date"], "isoformat") else customer["renewal_date"]
    final["generated_at"] = datetime.utcnow().isoformat()

    final["agent_trace"] = {
        "agents_run": ["deterministic_screen", "eligible_catalog", "recommendation"] + (["critic"] if draft.product else []),
        "decision_status": "qualified" if final.get("recommended_product") else "review_required" if fallbacks_used else "rejected" if not critic.approved else "no_opportunity",
        "evidence": evidence,
        "source_excerpt_attached": bool(evidence),
        "passed_validation_gates": bool(final.get("recommended_product") and not fallbacks_used and critic.approved),
        "model_tier": {"recommendation": LLM_MODEL, "others": LLM_MODEL},
        "retrieval_method": "eligible_filtered",  # no LLM involved either way
        "candidate_count": len(candidates.products),
        "candidate_products": [p.product_name for p in candidates.products],
        "critic_approved": critic.approved,
        "critic_veto_reason": critic.veto_reason,
        "critic_churn_risk_reason": critic.churn_risk_reason,
        "deal_value_anomaly": deal_value.anomaly_flag,
        "deal_value_anomaly_reason": deal_value.anomaly_reason,
        "fallbacks_used": fallbacks_used,
        # Real, evidence-grounded text from each agent's own output --
        # the frontend trace should render these instead of a generic
        # per-stage summary.
        "signal_reason": signal_result.reason,
        "signal_urgency": signal_result.urgency,
        "recommendation_rationale": final.get("rationale"),
        "recommended_product": final.get("recommended_product"),
        "churn_risk": final.get("churn_risk"),
        "revenue_score": final.get("revenue_score"),
        "confidence": final.get("confidence"),
        "estimated_deal_value": final.get("estimated_deal_value"),
    }
    if fallbacks_used:
        log.warning(
            "[%s] Heuristic fallback was used for: %s (live model unavailable for those steps).",
            customer_id, ", ".join(fallbacks_used),
        )
    log.info(
        "[%s] FINAL: product=%s churn=%s score=%s",
        customer_id, final["recommended_product"], final["churn_risk"], final["revenue_score"],
    )
    return final
