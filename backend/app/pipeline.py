"""
Orchestrator: calibration -> pre-filter -> reasoning -> ranked results.

Reasoning is multi-agent-only from the tenant's point of view. Every run
uses the IndiaAI multi-agent workflow (app/agents/workflow.py: signal ->
retrieval -> recommendation -> critic). Neither the legacy batched
path nor tenant_config's "llm_provider" are read anymore -- multi-agent
is not something a tenant opts into, it's the only path.
rule_based_recommendation() is NOT a mode a tenant can select -- it only
ever runs as an automatic, per-customer fallback when the 'agent-framework'
SDK or key is missing, or a live agent call fails, so a run still produces a
recommendation instead of silently dropping that customer. See
_fallback_to_rule_based().
"""

from datetime import datetime

from app import db
from app.logging_config import get_logger
from app.prefilter import passes_prefilter, estimate_churn_risk
from app.trust import eligible_catalog, evidence_supports_expansion, source_evidence
from app.rule_engine import rule_based_recommendation
from app.calibration import compute_tenant_profile
from app.dynamic_context import (
    build_dynamic_field_context,
    build_ticket_dynamic_field_context,
    build_usage_dynamic_field_context,
)
from app.agents.payload import is_schema_free_tenant, build_generic_customer_payload
from app.agents.pitch import build_pitch_recommendation
from app.agents.confidence import (
    compute_confidence,
    compute_data_completeness,
    compute_retrieval_fit,
)

log = get_logger(__name__)


def generate_recommendations(
    customer_ids: list[str] = None,
    limit: int = None,
    tenant_id: str = "default",
    force_include: bool = False,
    include_null_results: bool = False,
) -> list[dict]:
    """
    force_include=True skips the passes_prefilter() shortlist check for the
    given customer_ids -- used by the single-customer analyze endpoint,
    where a tenant explicitly asked to analyze one customer and shouldn't
    get an empty result just because that customer wouldn't normally have
    made the batch shortlist.

    include_null_results=True keeps customers whose recommended_product
    ended up null (whether from a Signal-agent rejection, a Critic veto, or
    the high-churn code gate -- see no_recommendation_reason_code in
    agents/workflow.py) in the returned list instead of silently dropping
    them. Default is False to preserve existing /run behavior (a batch run
    should only surface actionable leads, not every customer considered).
    Only these null-result entries are excluded from db.log_recommendation
    either way -- there's nothing to log for a customer with no product.
    """
    customers = db.get_customers(tenant_id, customer_ids)
    if limit:
        customers = customers[:limit]
    catalog = db.get_product_catalog(tenant_id)

    tenant_profile = db.get_tenant_profile(tenant_id)
    if tenant_profile is None:
        log.info("No calibration profile found for tenant '%s' -- computing now.", tenant_id)
        tenant_profile = compute_tenant_profile(tenant_id)

    tenant_config = db.get_tenant_config(tenant_id)
    use_vector_search = bool(tenant_config.get("use_vector_search", False))

    try:
        feature_weights = db.get_feature_weights(tenant_id)
    except Exception:
        feature_weights = {}

    shortlisted = []
    not_shortlisted = []
    for customer in customers:
        usage_rows = db.get_usage(tenant_id, customer["customer_id"])
        tickets = db.get_tickets(tenant_id, customer["customer_id"])
        if force_include or passes_prefilter(customer, usage_rows, tickets, tenant_profile):
            shortlisted.append((customer, usage_rows, tickets))
        else:
            not_shortlisted.append((customer, usage_rows, tickets))

    # Use only the configured IndiaAI Qwen gateway for multi-agent analysis.
    from app.indiaai_client import is_configured, make_client
    from app.config import LLM_PROVIDER
    llm_ready = False
    if is_configured():
        try:
            client = make_client()  # Validate configuration locally, no network call.
            client.close()
            from app.agents.workflow import build_agents, run_customer
            from app.agents.clients import close_clients
            llm_ready = True
        except (ImportError, RuntimeError) as exc:
            log.warning("%s client unavailable (%s) -- rule-based mode.", LLM_PROVIDER, exc)
    effective_mode = "indiaai_agents" if llm_ready else "rule"
    mode_label = f"{LLM_PROVIDER}-multi-agent" if llm_ready else "rule-based (LLM unavailable)"

    log.info(
        "Pipeline start (%s mode): tenant=%s customers=%d shortlisted=%d catalog=%d",
        mode_label, tenant_id, len(customers), len(shortlisted), len(catalog),
    )

    results = []
    recs_with_product = 0
    errors = 0

    if effective_mode == "indiaai_agents":
        import asyncio

        # How many customers to run concurrently. Each customer makes up to
        # 3 sequential IndiaAI calls (signal -> recommendation -> critic),
        # so this is really "how many concurrent IndiaAI requests" --
        # tune it down if you start hitting 429s on your deployment's
        # TPM/RPM quota, tune it up if you have headroom.
        import os
        MAX_CONCURRENT_CUSTOMERS = max(1, min(int(os.getenv("INDIAAI_CONCURRENCY", "1")), 8))
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CUSTOMERS)

        async def _run_one(customer, usage_rows, tickets, agents):
            nonlocal errors, recs_with_product
            async with semaphore:
                try:
                    signal_request = build_signal_request(customer, usage_rows, tickets, tenant_profile, tenant_id)
                    if feature_weights:
                        signal_request["feature_priorities"] = feature_weights
                    if (
                        signal_request["dynamic_fields"]
                        or signal_request["ticket_dynamic_fields"]
                        or signal_request["usage_dynamic_fields"]
                    ):
                        # DEBUG, not INFO -- this is a per-customer, per-run
                        # dump of every discovered field's raw value, useful
                        # while verifying the dynamic-field wiring but too
                        # noisy to leave at INFO once that's confirmed working.
                        log.debug(
                            "[%s] Dynamic fields in payload -- customer-level: %s, ticket-level: %s, usage-level: %s",
                            customer["customer_id"],
                            signal_request["dynamic_fields"],
                            signal_request["ticket_dynamic_fields"],
                            signal_request["usage_dynamic_fields"],
                        )
                    rec = await run_customer(
                        signal_request,
                        customer,
                        catalog,
                        agents,
                        tenant_id=tenant_id,
                    )
                    db.log_recommendation(tenant_id, rec)
                    if rec.get("recommended_product"):
                        recs_with_product += 1
                        results.append(rec)
                    elif include_null_results:
                        results.append(rec)
                except Exception as e:
                    log.warning(
                        "IndiaAI agent pipeline failed for %s (%s) -- falling back to "
                        "rule-based reasoning for this customer.", customer['customer_id'], e,
                    )
                    errors += 1
                    rec = {
                        "customer_id": customer["customer_id"], "customer_name": customer["customer_name"],
                        "segment": "review_required", "churn_risk": "medium", "churn_reason": str(e)[:180],
                        "recommended_product": None, "recommendation_type": None,
                        "rationale": "Live AI analysis unavailable; no automatically approved pitch.",
                        "revenue_score": 0, "confidence": 0, "estimated_deal_value": 0,
                        "no_recommendation_reason_code": "provider_error", "retention_action": None,
                        "renewal_date": str(customer.get("renewal_date") or ""), "generated_at": datetime.utcnow().isoformat(),
                        "agent_trace": {"decision_status": "review_required", "agents_run": [],
                                        "fallbacks_used": ["provider_error"]},
                    }
                    db.log_recommendation(tenant_id, rec)
                    if include_null_results:
                        results.append(rec)

        async def _run_all():
            agents = build_agents()
            try:
                await asyncio.gather(
                    *(
                        _run_one(customer, usage_rows, tickets, agents)
                        for customer, usage_rows, tickets in shortlisted
                    )
                )
            finally:
                # Close inside the same loop that created these clients --
                # closing after the loop exits is what caused the
                # "Event loop is closed" aclose() errors on shutdown.
                await close_clients()

        asyncio.run(_run_all())
    else:
        # Rule-based fallback when no IndiaAI key/SDK is configured.
        # No API calls or model charges.
        for customer, usage_rows, tickets in shortlisted:
            try:
                service_rows = db.get_service_usage(tenant_id, customer["customer_id"])
                rec = rule_based_recommendation(
                    customer, usage_rows, tickets, catalog, use_vector_search, service_rows, tenant_id=tenant_id
                )
                rec["customer_id"] = customer["customer_id"]
                rec["customer_name"] = customer["customer_name"]
                rec["renewal_date"] = customer["renewal_date"].isoformat()
                rec["estimated_deal_value"] = _estimate_deal_value(rec, customer, catalog)
                rec["generated_at"] = datetime.utcnow().isoformat()
                rec["confidence"] = _rule_based_confidence(customer, usage_rows, tickets, catalog, rec, tenant_id)
                # Offline rules are not an independent AI validation. Surface
                # these results as review-only, with zero qualified pipeline value.
                signal_request = {"usage_rows": usage_rows, "tickets": tickets}
                allowed, _ = eligible_catalog(catalog, customer, signal_request)
                names = {p["product_name"] for p in allowed}
                if (rec.get("recommended_product") not in names or
                        rec.get("churn_risk") == "high" or not evidence_supports_expansion(signal_request)):
                    rec["recommended_product"] = None
                rec["recommended_product"] = None
                rec["recommendation_type"] = None
                rec["confidence"] = 0
                rec["revenue_score"] = 0
                rec["no_recommendation_reason_code"] = "offline_review_required"
                rec["estimated_deal_value"] = 0
                rec["agent_trace"] = {"decision_status": "review_required", "agents_run": ["offline_rules"],
                    "evidence": source_evidence(customer, signal_request), "fallbacks_used": ["no_indiaai"]}
                log.info(
                    "[%s] Rule-based: product=%s churn=%s score=%s conf=%s",
                    customer["customer_id"], rec.get("recommended_product"),
                    rec.get("churn_risk"), rec.get("revenue_score"), rec.get("confidence"),
                )
                db.log_recommendation(tenant_id, rec)
                if rec.get("recommended_product"):
                    recs_with_product += 1
                    results.append(rec)
                elif include_null_results:
                    results.append(rec)
            except Exception as e:
                log.error("Rule-based reasoning failed for %s: %s", customer['customer_id'], e)
                errors += 1

    # The accounts not shortlisted are still saved for transparent review;
    # never fabricate a pitch, deal value or AI confidence for them.
    for customer, usage_rows, tickets in not_shortlisted:
        det_risk, det_reason = estimate_churn_risk(customer, usage_rows, tickets)
        rec = {
            "customer_id": customer["customer_id"], "customer_name": customer["customer_name"],
            "segment": "not_shortlisted", "churn_risk": det_risk, "churn_reason": det_reason,
            "recommended_product": None, "recommendation_type": None, "rationale": det_reason,
            "revenue_score": 0, "confidence": 0, "estimated_deal_value": 0,
            "no_recommendation_reason_code": "not_shortlisted", "retention_action": None,
            "renewal_date": str(customer.get("renewal_date") or ""), "generated_at": datetime.utcnow().isoformat(),
            "agent_trace": {"decision_status": "not_shortlisted", "agents_run": ["prefilter"],
                            "fallbacks_used": [], "reason_code": "not_shortlisted"},
        }
        db.log_recommendation(tenant_id, rec)
        if include_null_results:
            results.append(rec)

    results.sort(key=lambda r: r["revenue_score"], reverse=True)

    log.info(
        "Pipeline complete (%s mode): %d customers, %d shortlisted, %d errors, %d recommendations generated.",
        mode_label, len(customers), len(shortlisted), errors, recs_with_product,
    )
    return results


def _fallback_to_rule_based(
    customer: dict,
    usage_rows: list[dict],
    tickets: list[dict],
    catalog: list[dict],
    use_vector_search: bool,
    results: list[dict],
    tenant_id: str,
    include_null_results: bool = False,
) -> bool:
    """
    Runs the deterministic rule-based path for a single customer and appends
    the result to `results` in place. Used whenever an LLM/agent provider is
    configured but turns out to be unavailable or fails at run time, so a
    tenant's run still produces a recommendation instead of silently
    dropping that customer.

    tenant_id must be passed explicitly -- this is a module-level function,
    not a closure over the caller's tenant_id, so relying on an outer-scope
    name here would raise NameError at call time.

    Returns True if a product was actually recommended (for the caller's
    recs_with_product tally), False otherwise.
    """
    try:
        service_rows = db.get_service_usage(tenant_id, customer["customer_id"])
        rec = rule_based_recommendation(
            customer, usage_rows, tickets, catalog, use_vector_search, service_rows, tenant_id=tenant_id
        )
        rec["customer_id"] = customer["customer_id"]
        rec["customer_name"] = customer["customer_name"]
        rec["renewal_date"] = customer["renewal_date"].isoformat()
        rec["estimated_deal_value"] = _estimate_deal_value(rec, customer, catalog)
        rec["generated_at"] = datetime.utcnow().isoformat()
        rec["reasoning_mode"] = "rule-based (fallback)"
        rec["confidence"] = _rule_based_confidence(customer, usage_rows, tickets, catalog, rec, tenant_id)
        db.log_recommendation(tenant_id, rec)
        has_product = bool(rec.get("recommended_product"))
        if has_product or include_null_results:
            results.append(rec)
        return has_product
    except Exception as e:
        log.error("Rule-based fallback also failed for %s: %s", customer["customer_id"], e)
        return False


def _rule_based_confidence(
    customer: dict, usage_rows: list[dict], tickets: list[dict],
    catalog: list[dict], rec: dict, tenant_id: str,
) -> float:
    """Confidence for a deterministic rule-based result. Passed
    used_fallbacks=['recommendation'] so a rule-based row (produced only when
    the LLM/agent path is unavailable) is penalized the same way a heuristic
    fallback is -- it should never outrank a genuine live-model match."""
    return compute_confidence(
        llm_confidence=None,
        data_completeness=compute_data_completeness(customer, usage_rows, tickets, None, tenant_id),
        retrieval_fit=compute_retrieval_fit(
            catalog, customer.get("plan_tier"), rec.get("recommended_product"),
        ),
        used_fallbacks=["recommendation"],
        is_low_confidence_pitch=False,
        has_product=bool(rec.get("recommended_product")),
    )


def _estimate_deal_value(rec: dict, customer: dict, catalog: list[dict]) -> float:
    recommended = rec.get("recommended_product")
    if not recommended:
        return 0.0
    # Match by id or name -- rule_engine.py sets this to product_name, but
    # keep this tolerant in case that ever changes (see same fix in
    # llm_engine.py, which has to handle the LLM returning either).
    product = next(
        (p for p in catalog if p["product_id"] == recommended or p["product_name"] == recommended),
        None,
    )
    if not product:
        return 0.0
    return round(product["price_per_seat"] * customer["seats"] * 12, 2)


def build_signal_request(
    customer: dict, usage_rows: list[dict], tickets: list[dict],
    tenant_profile: dict | None = None, tenant_id: str = "default",
) -> dict:
    """Build the initial signal request payload for the IndiaAI signal workflow.

    Includes `dynamic_fields` -- tenant-specific columns discovered at
    ingestion time (see app.dynamic_context) -- so they reach every agent
    that reads this payload or a superset of it: signal (direct), retrieval
    (folded into the vector-search query text in agents/workflow.py), and
    recommendation (customer_signal_request is spread into its input).
    Only the critic agent needs this added separately, since it deliberately
    builds a narrower input (see agents/workflow.py).

    Also includes `ticket_dynamic_fields` and `usage_dynamic_fields` for the
    same reason, but scoped to dataset_type "support_tickets" and
    "usage_metrics" respectively -- a discovered column like
    "Priority_Score" or a renamed/extra usage metric lives on ticket/usage
    rows, not customer rows, and would otherwise never get the same
    name/description treatment dynamic_fields gets (see
    app.dynamic_context.build_ticket_dynamic_field_context and
    build_usage_dynamic_field_context).

    Stage 4 (schema_free_pipeline_design.md §4): also merges in a generic
    `datasets` key -- the same `{"dataset_label", "schema", "rows"}` shape
    Stage 3's sample check already builds against tenant_records, but
    scoped to this one customer and sourced live via
    app.agents.payload.build_generic_customer_payload(). This is a MERGE,
    not a replacement of the fixed keys above: every agent prompt still
    reads customer_profile/usage_rows/tickets/dynamic_fields exactly as
    before (so nothing here breaks against the golden-set tests, which
    exercise the agents with that fixed shape directly), while an agent
    that's been told to also look at `datasets` gets the tenant's true
    discovered columns straight from Stage 1, including any column that
    isn't one of the fixed usage/ticket dynamic-field categories at all
    (e.g. a customer-scoped dataset with no dataset_type equivalent in the
    old model). `datasets` is `[]` for a tenant with no Stage-1-discovered
    data (i.e. never run through the schema-free/migration path) -- safe
    to always include."""
    generic_payload = (
        build_generic_customer_payload(tenant_id, customer["customer_id"])
        if is_schema_free_tenant(tenant_id)
        else {"customer_id": customer.get("customer_id"), "datasets": []}
    )
    return {
        "customer_profile": customer,
        "usage_rows": usage_rows,
        "tickets": tickets,
        "tenant_profile": tenant_profile,
        "dynamic_fields": build_dynamic_field_context(tenant_id, customer, dataset_type="customers"),
        "ticket_dynamic_fields": build_ticket_dynamic_field_context(tenant_id, tickets),
        "usage_dynamic_fields": build_usage_dynamic_field_context(tenant_id, usage_rows),
        "datasets": generic_payload["datasets"],
    }
