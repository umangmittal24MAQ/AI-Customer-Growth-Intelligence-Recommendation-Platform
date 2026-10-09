import json

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app.logging_config import get_logger
from app.pipeline import generate_recommendations
from app import db
from app.models import RunResponse, OutcomeUpdate
from app.calibration import recalibrate_from_feedback, compute_tenant_profile
from app import vector_engine
from app.citation import raw_column_citation, dynamic_field_citation, agent_trace_citation
from app.usage_rollup import compute_feature_usage_score
from app.web_api import router as frontend_router
from app.auth import get_current_tenant
from app import accounts

log = get_logger(__name__)

app = FastAPI(title="Traject")

# The React frontend is served from a separate dev server (Vite on :5173) and
# proxies /api to this app. Allow cross-origin calls so the app also works if
# the frontend is pointed straight at the backend instead of through the proxy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in __import__("os").getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Frontend-facing REST contract (/api/*) mapped onto the backend data/pipeline.
app.include_router(frontend_router)


@app.on_event("startup")
def _log_startup():
    # Creates every table if it doesn't exist yet, and the DB file itself
    # if it doesn't exist -- data itself is loaded directly into the SQL
    # database (see data/generate_synthetic_data.py, or write your own
    # loader against data/schema.sql) rather than through an upload API.
    db.init_db()
    log.info("Database ready at %s.", db.DB_PATH)

    from app.indiaai_client import is_configured, make_client
    from app.config import LLM_PROVIDER, LLM_MODEL
    if not is_configured():
        log.warning("%s API key not configured; analysis uses deterministic fallback.", LLM_PROVIDER)
    else:
        try:
            client = make_client()  # No inference request is sent.
            client.close()
            log.info("%s configured; model=%s; multi-agent reasoning enabled.", LLM_PROVIDER, LLM_MODEL)
        except (ImportError, RuntimeError) as exc:
            log.warning("%s unavailable (%s); analysis uses deterministic fallback.", LLM_PROVIDER, exc)

    log.info("Traject API started. Logs also written to logs/traject.log")


class TenantConfigRequest(BaseModel):
    use_llm: bool = True
    llm_provider: str | None = "indiaai"
    use_vector_search: bool = False
    # "recurring" (SaaS -- price_per_seat is a monthly rate) or "one_time"
    # (retail/goods -- price_per_seat is a per-unit price). None leaves any
    # existing stored value untouched (see db.set_tenant_config).
    revenue_model: str | None = None


@app.get("/")
def root():
    return {"status": "ok", "service": "Traject"}


class SignupRequest(BaseModel):
    client_name: str
    email: str
    password: str
    confirm_password: str
    domain: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/auth/signup")
def signup(payload: SignupRequest):
    """Self-service tenant signup -- see app/accounts.py. Creates a new
    tenant_id (derived from client_name), an API key, and the
    email/password account row, then auto-ingests any CSVs already sitting
    under data/tenant_uploads/<tenant_id>/ (same bootstrap step the legacy
    tenant-id-only login flow used)."""
    try:
        return accounts.sign_up(
            payload.client_name,
            payload.email,
            payload.password,
            payload.confirm_password,
            domain=payload.domain,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/login")
def login(payload: LoginRequest):
    """Email + password login (see app/accounts.py) -- replaces the old
    tenant-id-only login. Verifies the password server-side (PBKDF2,
    salted per-account) and, on success, reissues a fresh api_key for that
    tenant the same way the legacy flow did. The frontend stores the
    returned api_key in sessionStorage and attaches it on every later
    request via X-Tenant-Id/X-API-Key -- unchanged from before, the user
    just now authenticates with real credentials to get one."""
    try:
        return accounts.log_in(payload.email, payload.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/run", response_model=RunResponse)
def run_pipeline(tenant_id: str = Depends(get_current_tenant)):
    log.info("POST /run received -- starting pipeline for tenant=%s.", tenant_id)
    results = generate_recommendations(tenant_id=tenant_id)
    log.info("POST /run finished -- %d recommendations returned.", len(results))
    return {
        "count": len(results),
        "recommendations": results,
        "total_customers": len(db.get_customers(tenant_id)),
        "total_catalog_products": len(db.get_product_catalog(tenant_id)),
    }


@app.get("/recommendations")
def get_recommendations(min_score: float = 0, tenant_id: str = Depends(get_current_tenant)):
    results = db.get_latest_recommendations(tenant_id)
    for r in results:
        trace_raw = r.get("agent_trace")
        try:
            r["agent_trace"] = json.loads(trace_raw) if trace_raw else None
        except (TypeError, json.JSONDecodeError):
            r["agent_trace"] = None
        r["field_citations"] = _recommendation_citations(r)
    return [r for r in results if r["revenue_score"] >= min_score]


def _recommendation_citations(rec: dict) -> dict:
    """Provenance for the reasoning-derived fields on a recommendation --
    what step produced them and what inputs they're based on, for a
    frontend hover/info-icon to show as validation."""
    trace = rec.get("agent_trace") or {}
    based_on = list(trace.keys()) if isinstance(trace, dict) else []
    return {
        "churn_risk": agent_trace_citation(rec.get("churn_risk"), "churn_risk_scoring", based_on),
        "recommended_product": agent_trace_citation(rec.get("recommended_product"), "recommendation_engine", based_on),
        "revenue_score": agent_trace_citation(rec.get("revenue_score"), "revenue_scoring", based_on),
        "estimated_deal_value": agent_trace_citation(
            rec.get("estimated_deal_value"), "deal_value_estimate",
            based_on=["product_catalog.price_per_seat", "customers.seats"],
        ),
    }


@app.get("/recommendations/{rec_id}/trace")
def get_recommendation_trace(rec_id: int, tenant_id: str = Depends(get_current_tenant)):
    """
    Returns the full explainability record for one recommendation: the
    parsed agent_trace (which agents ran, model tier, critic verdict,
    retrieval method, deal-value anomaly) plus the final recommendation
    fields, so a dashboard can show the whole reasoning chain without the
    caller needing to know it's stored as a JSON string in SQLite.
    """
    rec = db.get_recommendation_by_id(tenant_id, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    trace_raw = rec.get("agent_trace")
    try:
        trace = json.loads(trace_raw) if trace_raw else None
    except (TypeError, json.JSONDecodeError):
        trace = None
    rec["agent_trace"] = trace
    rec["field_citations"] = _recommendation_citations(rec)
    return rec


@app.get("/customer/{customer_id}")
def get_customer_detail(customer_id: str, tenant_id: str = Depends(get_current_tenant)):
    """
    Returns the customer's full profile (core fields, usage, tickets,
    per-service usage). Also includes `field_citations` -- provenance info
    for the fields a frontend hover/info-icon can bind to (source, how it
    was derived, and for tenant-specific dynamic fields, an LLM-written
    description) -- without changing the shape of the existing fields, so
    nothing that already reads this endpoint breaks.
    """
    profile = db.get_customer_full_profile(tenant_id, customer_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Customer not found")

    field_citations = {
        "plan_tier": raw_column_citation(profile.get("plan_tier")),
        "seats": raw_column_citation(profile.get("seats")),
        "renewal_date": raw_column_citation(str(profile.get("renewal_date"))),
    }

    # Per-service usage breakdown replaces the old opaque feature_usage_score
    # -- citable back to exactly which services drove it.
    rollup = compute_feature_usage_score(tenant_id, customer_id)
    field_citations["feature_usage_score"] = agent_trace_citation(
        rollup["score"],
        agent_step="usage_rollup",
        based_on=[f"service_usage.{b['service_name']}" for b in rollup["based_on"]],
    )
    profile["feature_usage_score"] = rollup["score"]
    profile["feature_usage_breakdown"] = rollup["based_on"]

    # Tenant-specific dynamic fields (customers dataset) -- each one gets
    # its own citation pointing back to the LLM's classification.
    for entry in db.get_dynamic_fields(tenant_id, dataset_type="customers"):
        value = profile.get("extra_attributes", {}).get(entry["field_name"])
        field_citations[entry["field_name"]] = dynamic_field_citation(value, entry)

    # Ticket-level dynamic fields (e.g. Priority_Score) -- these were being
    # silently dropped here even after app.dynamic_context started feeding
    # them into reasoning; a citation is now added per (ticket, field) pair
    # so a frontend hover/info-icon can explain them the same way it does
    # for customer-level fields.
    ticket_fields = db.get_dynamic_fields(tenant_id, dataset_type="support_tickets")
    if ticket_fields:
        for ticket in profile.get("tickets", []):
            raw = ticket.get("extra_attributes")
            extra = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
            for entry in ticket_fields:
                value = extra.get(entry["field_name"])
                if value is None:
                    continue
                key = f"ticket:{ticket.get('ticket_id')}:{entry['field_name']}"
                field_citations[key] = dynamic_field_citation(value, entry)

    # Usage-level dynamic fields (e.g. a renamed/extra usage metric) --
    # same treatment, keyed by month since the same field can carry a
    # different value per usage row.
    usage_fields = db.get_dynamic_fields(tenant_id, dataset_type="usage_metrics")
    if usage_fields:
        for usage_row in profile.get("usage", []):
            extra = usage_row.get("extra_attributes") or {}
            for entry in usage_fields:
                value = extra.get(entry["field_name"])
                if value is None:
                    continue
                key = f"usage:{usage_row.get('month')}:{entry['field_name']}"
                field_citations[key] = dynamic_field_citation(value, entry)

    profile["field_citations"] = field_citations
    return profile


@app.post("/customer/{customer_id}/analyze")
def analyze_single_customer(customer_id: str, tenant_id: str = Depends(get_current_tenant)):
    """
    Runs the full reasoning pipeline for exactly one customer -- same
    scoring/rationale logic as POST /run, but skips the batch shortlist
    across the tenant's whole roster. Useful when a client wants to check
    or re-check one account without an unnecessary full-dataset run.

    force_include=True on the underlying call means this always produces a
    result for the requested customer, even if they wouldn't normally have
    made the batch shortlist (e.g. no notable usage/renewal signal) --
    since the tenant explicitly asked to analyze this one.
    """
    if not db.get_customers(tenant_id, [customer_id]):
        raise HTTPException(status_code=404, detail="Customer not found")

    results = generate_recommendations(
        customer_ids=[customer_id], tenant_id=tenant_id, force_include=True, include_null_results=True,
    )
    if not results:
        # Genuinely unexpected at this point -- include_null_results=True
        # means every outcome (signal rejection, critic veto, high-churn
        # gate, no-opportunity-found) comes back as a result now. An empty
        # list here means the pipeline itself errored for this customer
        # (see errors count in the pipeline-complete log), not a normal
        # "no recommendation" outcome.
        return {
            "customer_id": customer_id,
            "recommendation": None,
            "no_recommendation_reason_code": "pipeline_error",
            "reason": "No result was produced at all -- the reasoning pipeline likely errored "
                      "for this customer rather than reaching a null-recommendation verdict. "
                      "Check server logs for this customer_id.",
        }
    rec = results[0]
    if not rec.get("recommended_product"):
        rec["recommendation"] = None
        rec["reason"] = rec.get("churn_reason") or rec.get("rationale")
    rec["field_citations"] = _recommendation_citations(rec)
    return rec
    return rec


@app.post("/recommendations/{rec_id}/outcome")
def log_outcome(rec_id: int, update: OutcomeUpdate, tenant_id: str = Depends(get_current_tenant)):
    if update.outcome not in ("accepted", "rejected", "converted"):
        raise HTTPException(status_code=400, detail="Invalid outcome value")
    updated = db.update_outcome(tenant_id, rec_id, update.outcome)
    if not updated:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return {"status": "ok", "id": rec_id, "outcome": update.outcome}


@app.get("/tenant/{tenant_id}/profile")
def get_tenant_profile(tenant_id: str, authorized_tenant: str = Depends(get_current_tenant)):
    if tenant_id != authorized_tenant:
        raise HTTPException(status_code=403, detail="API key does not match requested tenant_id")
    profile = db.get_tenant_profile(tenant_id)
    if not profile:
        raise HTTPException(status_code=404, detail="No calibration profile yet -- run /run first")
    return profile


@app.post("/tenant/{tenant_id}/recalibrate")
def trigger_recalibration(tenant_id: str, authorized_tenant: str = Depends(get_current_tenant)):
    """Manual trigger for feedback-based recalibration -- normally runs weekly via the scheduler."""
    if tenant_id != authorized_tenant:
        raise HTTPException(status_code=403, detail="API key does not match requested tenant_id")
    profile = recalibrate_from_feedback(tenant_id)
    if profile is None:
        return {"status": "skipped", "reason": "not enough logged outcomes yet (need 20+)"}
    return {"status": "recalibrated", "profile": profile}


@app.get("/tenant/{tenant_id}/config")
def get_tenant_config(tenant_id: str, authorized_tenant: str = Depends(get_current_tenant)):
    if tenant_id != authorized_tenant:
        raise HTTPException(status_code=403, detail="API key does not match requested tenant_id")
    return db.get_tenant_config(tenant_id)


@app.post("/tenant/{tenant_id}/config")
def set_tenant_config(tenant_id: str, config: TenantConfigRequest, authorized_tenant: str = Depends(get_current_tenant)):
    """
    Sets which AI provider writes the explanations for this tenant.
    AI-written explanations are always on; there is no rule-based-only mode
    to pick here -- if the chosen provider is unavailable at run time
    (missing dependency, missing API key, rate limit, etc.), the pipeline
    automatically falls back to the deterministic rule-based reasoning for
    the affected customers so a run never fails outright.
    """
    if tenant_id != authorized_tenant:
        raise HTTPException(status_code=403, detail="API key does not match requested tenant_id")
    llm_provider = "indiaai"
    if config.use_vector_search and not vector_engine.is_available():
        raise HTTPException(
            status_code=400,
            detail="Vector search requires the 'sentence-transformers' package. "
                   "Install it with: pip install sentence-transformers",
        )
    if config.revenue_model is not None and config.revenue_model not in ("recurring", "one_time"):
        raise HTTPException(
            status_code=400,
            detail="revenue_model must be 'recurring' or 'one_time'",
        )
    db.set_tenant_config(tenant_id, True, llm_provider, config.use_vector_search, config.revenue_model)
    updated_config = db.get_tenant_config(tenant_id)
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "use_llm": True,
        "llm_provider": llm_provider,
        "use_vector_search": config.use_vector_search,
        "revenue_model": updated_config.get("revenue_model", "recurring"),
    }


@app.get("/catalog/embeddings/status")
def catalog_embedding_status(tenant_id: str = Depends(get_current_tenant)):
    """
    Reports whether the vector-search dependency is installed and how much
    of the current catalog has embeddings stored. Used by the dashboard to
    decide whether to offer the "enable vector search" toggle at all.
    """
    catalog = db.get_product_catalog(tenant_id)
    pending = vector_engine.catalog_needs_embedding(catalog, tenant_id) if vector_engine.is_available() else []
    return {
        "vector_search_available": vector_engine.is_available(),
        "total_products": len(catalog),
        "embedded_products": len(catalog) - len(pending),
        "pending_products": pending,
    }


@app.post("/catalog/embed")
def embed_catalog(tenant_id: str = Depends(get_current_tenant)):
    """
    Embeds every product in the catalog that doesn't already have a stored
    embedding. Safe to call repeatedly (already-embedded products are
    skipped by find_similar_products lookups being keyed on product_id --
    re-run just refreshes anything missing, e.g. after adding new products).
    """
    if not vector_engine.is_available():
        raise HTTPException(
            status_code=400,
            detail="Vector search requires the 'sentence-transformers' package. "
                   "Install it with: pip install sentence-transformers",
        )
    catalog = db.get_product_catalog(tenant_id)
    count = vector_engine.embed_and_store_catalog(catalog, tenant_id)
    return {"status": "ok", "embedded": count, "total_products": len(catalog)}