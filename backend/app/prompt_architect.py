"""
Prompt Architect Agent (Stage 2 of the schema-free ingestion pipeline).
See schema_free_pipeline_design.md for the full design.

Takes the combined column catalog across all of a tenant's datasets
(app.db.get_tenant_schema_catalog, populated by Stage 1's schema_discovery.py)
and writes the tenant-specific instruction block the reasoning agents
(Signal, Retrieval, Recommendation, Critic) will use -- naming which columns
cover which concepts, which insight categories are possible for this tenant,
and which to skip because the data to support them doesn't exist.

Compiled once and CACHED in tenant_prompt_specs, keyed by a fingerprint of
the tenant's current dataset schema_versions -- re-triggered only when a
re-upload actually changes something (see compile_if_stale()). This matters
because:
  - Cost/latency: regenerating it per-analysis-call doubles LLM calls for
    no new information.
  - Consistency: two customers from the same tenant must be scored against
    the same framing, or cross-customer comparison breaks.
  - Debuggability: an LLM-authored prompt fed to another LLM, freshly
    re-derived every call, is very hard to reason about when something
    looks wrong.
"""

import hashlib
import json

from app.indiaai_client import optional_client

from app.config import LLM_MODEL
from app.logging_config import get_logger
from app import db

log = get_logger(__name__)

# The full set of insight categories the reasoning agents know how to
# produce, if the tenant's data supports them. Core ones are always
# attempted (data_gaps warning if unsupported); dynamic/custom ones are
# pure add/omit. See §5 of the design doc.
CORE_INSIGHT_CATEGORIES = ["churn_risk", "revenue_opportunity"]
KNOWN_DYNAMIC_CATEGORIES = [
    "nps_trend", "support_sentiment", "usage_adoption", "contract_health",
    "feature_engagement", "billing_anomaly",
]


def _client() -> object | None:
    return optional_client()


def compute_schema_fingerprint(tenant_id: str) -> str:
    """Hash of every dataset's schema_version for this tenant. Changes iff
    any dataset was re-uploaded with a different column set/dtypes -- the
    signal compile_if_stale() uses to decide whether to re-run Stage 2."""
    datasets = db.list_tenant_datasets(tenant_id)
    versions = sorted(f"{d['dataset_label']}:{d['schema_version']}" for d in datasets)
    return hashlib.sha256(json.dumps(versions).encode()).hexdigest()[:16]


def _fallback_prompt_spec(catalog: list[dict]) -> dict:
    """Used only if the LLM is unavailable/fails -- never blocks analysis.
    Conservative: lists the known columns plainly, attempts only the core
    categories, and excludes every dynamic category (safer to omit an
    insight than to reason about tenant data no one has actually vetted)."""
    by_dataset = {}
    for col in catalog:
        by_dataset.setdefault(col["dataset_label"], []).append(col["column_name"])
    lines = [f"- {label}: columns {cols}" for label, cols in by_dataset.items()]
    prompt_spec = (
        "This tenant's available data (auto-listed, not yet reviewed by the Prompt "
        "Architect Agent):\n" + "\n".join(lines) +
        "\n\nOnly reason using columns you can see in the data provided per customer. "
        "If a concept you need (renewal date, usage trend, etc.) isn't clearly present, "
        "say so explicitly rather than guessing a value."
    )
    return {
        "prompt_spec": prompt_spec,
        "possible_insight_categories": list(CORE_INSIGHT_CATEGORIES),
        "excluded_insight_categories": [
            {"category": c, "reason": "Prompt Architect Agent unavailable -- excluded conservatively."}
            for c in KNOWN_DYNAMIC_CATEGORIES
        ],
    }


def architect_prompt(tenant_id: str) -> dict:
    """
    Runs Stage 2 for one tenant (no caching -- caller decides via
    compile_if_stale whether this needs to run at all).

    Returns: {"prompt_spec": str, "possible_insight_categories": [...],
              "excluded_insight_categories": [{"category":..., "reason":...}, ...]}
    """
    catalog = db.get_tenant_schema_catalog(tenant_id)
    if not catalog:
        return _fallback_prompt_spec(catalog)

    client = _client()
    if client is None:
        log.warning("No IndiaAI key -- using conservative fallback prompt spec for tenant '%s'.", tenant_id)
        return _fallback_prompt_spec(catalog)

    # Trim to what the LLM needs: column, description, dtype, semantic_role,
    # relevance, concept, dataset_label. Raw stats/sample values already did
    # their job in Stage 1 and would just bloat this prompt.
    slim_catalog = [
        {
            "dataset": c["dataset_label"],
            "column": c["column_name"],
            "label": c["inferred_label"],
            "description": c["description"],
            "dtype": c["dtype"],
            "semantic_role": c["semantic_role"],
            "relevance": c["relevance"],
            "concept": c["concept"],
        }
        for c in catalog
    ]

    prompt = f"""You are writing a tenant-specific instruction block for downstream reasoning agents
(Signal, Retrieval, Recommendation, Critic) in a churn/upsell analysis pipeline. These agents will
receive this tenant's actual customer data at analysis time -- your job is to tell them, up front,
how to interpret THIS tenant's schema so they don't have to guess.

This tenant's combined column catalog (from Stage-1 schema discovery, across all their uploaded files):
{json.dumps(slim_catalog, indent=2)}

Known insight categories the pipeline can produce, IF the data supports them:
  Core (always attempted, gap reported if unsupported): {json.dumps(CORE_INSIGHT_CATEGORIES)}
  Dynamic/optional (pure add/omit, no gap warning if absent): {json.dumps(KNOWN_DYNAMIC_CATEGORIES)}

Write:
1. "prompt_spec": a concise instruction block (plain text, a few short paragraphs) that:
   - Explains how this tenant tracks health/value using the SPECIFIC columns found (name them).
   - Flags any core concept (renewal date, usage trend, pricing) that has NO mapped column, so
     agents infer proxies where reasonable or explicitly say the data is missing rather than guess.
   - Tells agents which columns to IGNORE (foreign keys, noise, admin-only fields) and why.
   - Lists which insight categories are realistically possible for this tenant's data and which are
     not (explicitly say "Do NOT attempt: X (no supporting data found)" for excluded ones).
2. "possible_insight_categories": array of category names (from the two lists above) this tenant's
   data can actually support.
3. "excluded_insight_categories": array of {{"category": ..., "reason": ...}} for every category NOT
   in possible_insight_categories.

Return ONLY a JSON object with exactly these three keys. No preamble, no markdown fences."""

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        if not result.get("prompt_spec"):
            raise ValueError("empty prompt_spec in LLM response")
        result.setdefault("possible_insight_categories", list(CORE_INSIGHT_CATEGORIES))
        result.setdefault("excluded_insight_categories", [])
        return result
    except Exception as e:
        log.warning("Prompt Architect LLM call failed for tenant '%s' (%s) -- using fallback.", tenant_id, e)
        return _fallback_prompt_spec(catalog)


def compile_if_stale(tenant_id: str, force: bool = False) -> dict:
    """
    Entry point callers (ingestion/onboarding flow, or Stage 3's self-
    correction loop) should use. Only re-runs Stage 2 if the tenant's
    schema_fingerprint changed since the last compile, or if force=True.
    Returns the cached or freshly-compiled spec either way.
    """
    fingerprint = compute_schema_fingerprint(tenant_id)
    cached = db.get_tenant_prompt_spec(tenant_id)
    if cached and cached.get("schema_fingerprint") == fingerprint and not force:
        log.info("Tenant '%s' prompt spec unchanged (fingerprint match) -- using cached compile.", tenant_id)
        return cached

    log.info("Compiling Stage-2 prompt spec for tenant '%s' (stale or forced).", tenant_id)
    result = architect_prompt(tenant_id)
    db.save_tenant_prompt_spec(
        tenant_id, result["prompt_spec"], result["possible_insight_categories"],
        result["excluded_insight_categories"], fingerprint,
    )
    return db.get_tenant_prompt_spec(tenant_id)
