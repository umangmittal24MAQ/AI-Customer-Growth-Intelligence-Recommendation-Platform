"""
Bounded self-correction loop (Stage 3 of the schema-free ingestion pipeline).
See schema_free_pipeline_design.md for the full design.

Ingestion-time only -- NEVER runs at analysis-time. Before a tenant's
compiled (schema, prompt_spec) is treated as final, this runs the check
against a small sample of real customers (3-5):

  1. Run a lightweight check against the Stage-2 prompt_spec for each
     sampled customer.
  2. Collect structured missing_concept / low_confidence flags -- cases
     where the check couldn't find something it expected (e.g. "no
     churn-relevant metric found").
  3. Feed flags back to schema_discovery.reexamine_concept(): "re-examine
     raw columns for anything mapping to X, or confirm it's genuinely
     absent."
  4. Repeat, capped at MAX_ITERATIONS. Whatever's unresolved after that is
     recorded as a data gap (tenant_schema_gaps) rather than looped on
     indefinitely.

Runtime cost: a few seconds to ~a couple minutes -- shown to the tenant as
"analyzing your data structure..." during onboarding, never during a live
analysis call.
"""

import json

from app.indiaai_client import optional_client

from app.config import LLM_MODEL
from app.logging_config import get_logger
from app import db
from app import schema_discovery
from app import prompt_architect

log = get_logger(__name__)

SAMPLE_SIZE = 5
MAX_ITERATIONS = 3


def _client() -> object | None:
    return optional_client()


def _sample_customer_ids(tenant_id: str, n: int = SAMPLE_SIZE) -> list[str]:
    """Pulls up to n distinct entity_ids from whichever dataset looks like
    the tenant's primary entity table (has a join_key_column pointing at
    itself, i.e. its own rows ARE the customers -- typically dataset_label
    'customers' or similar)."""
    datasets = db.list_tenant_datasets(tenant_id)
    entity_dataset = next((d for d in datasets if d["dataset_label"] == "customers"), None) \
        or next((d for d in datasets if d.get("join_key_column")), None)
    if not entity_dataset:
        return []
    rows = db.get_dataset_rows(tenant_id, entity_dataset["id"])
    join_key = entity_dataset.get("join_key_column")
    if not join_key:
        return []
    ids = [str(r[join_key]) for r in rows if r.get(join_key)]
    return ids[:n]


def _assemble_customer_payload(tenant_id: str, entity_id: str) -> dict:
    """Generic cross-dataset payload for one customer -- same shape
    build_signal_request() will eventually consume (see §4 of the design
    doc), gathered here directly from tenant_records rather than the old
    fixed tables."""
    datasets = db.list_tenant_datasets(tenant_id)
    payload = {"customer_id": entity_id, "datasets": []}
    for d in datasets:
        rows = [r for r in db.get_dataset_rows(tenant_id, d["id"])
                if str(r.get(d.get("join_key_column"), "")) == entity_id] if d.get("join_key_column") else []
        # Datasets with no join key (e.g. product_catalog) are tenant-wide,
        # not customer-specific -- included only for context, capped small.
        if not d.get("join_key_column"):
            rows = db.get_dataset_rows(tenant_id, d["id"])[:5]
        payload["datasets"].append({"dataset_label": d["dataset_label"], "rows": rows})
    return payload


def _run_check(prompt_spec: str, customer_payload: dict) -> dict:
    """One lightweight LLM check: given the tenant's Stage-2 prompt_spec and
    one customer's cross-dataset data, can churn_risk/revenue_opportunity
    reasoning actually proceed? Returns structured flags, never raises --
    an LLM failure here just means this customer contributes no flags
    (conservative: nothing new gets marked as a gap that isn't already)."""
    client = _client()
    if client is None:
        return {"flags": []}

    prompt = f"""Tenant-specific instructions for reasoning about this tenant's customers:
{prompt_spec}

One sample customer's cross-dataset data:
{json.dumps(customer_payload, indent=2, default=str)}

You are about to attempt churn_risk and revenue_opportunity analysis for this customer using ONLY
the data above. For each of those two categories, decide if you have enough signal to proceed.

Return ONLY a JSON object: {{"flags": [{{"concept": "..."|null, "flag_type": "missing_concept"|"low_confidence",
"detail": "..."}}]}}. Only include a flag if something you'd need is genuinely missing or too weak to
trust -- an empty flags list means you're confident you can proceed for both categories. No preamble,
no markdown fences."""

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL, temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        return {"flags": result.get("flags", [])}
    except Exception as e:
        log.warning("Stage-3 sample check LLM call failed (%s) -- treating as no flags for this customer.", e)
        return {"flags": []}


def run_self_correction(tenant_id: str) -> dict:
    """
    Entry point -- call once per ingestion/onboarding run, after Stage 1
    has discovered all of a tenant's current files and Stage 2 has compiled
    a prompt spec. Mutates tenant_schema_columns (via reexamine_concept)
    and tenant_schema_gaps as a side effect; returns a summary.
    """
    db.clear_tenant_schema_gaps(tenant_id)
    sample_ids = _sample_customer_ids(tenant_id, SAMPLE_SIZE)
    if not sample_ids:
        log.info("Stage 3: no sample customers found for tenant '%s' -- skipping self-correction.", tenant_id)
        return {"ran": False, "reason": "no customer entity rows found", "resolved": [], "unresolved": []}

    resolved_log = []
    unresolved_log = []
    outstanding_flags: list[dict] = []

    for iteration in range(1, MAX_ITERATIONS + 1):
        spec = prompt_architect.compile_if_stale(tenant_id)
        prompt_spec = spec["prompt_spec"]

        all_flags = []
        for cid in sample_ids:
            payload = _assemble_customer_payload(tenant_id, cid)
            check = _run_check(prompt_spec, payload)
            for f in check["flags"]:
                f["_customer_id"] = cid
            all_flags.extend(check["flags"])

        if not all_flags:
            log.info("Stage 3 tenant '%s': no flags on iteration %d -- self-correction converged.",
                      tenant_id, iteration)
            break

        # Group by concept (flags with no concept can't be re-examined --
        # they go straight to unresolved).
        by_concept: dict[str, list[dict]] = {}
        for f in all_flags:
            concept = f.get("concept")
            if not concept:
                unresolved_log.append(f)
                continue
            by_concept.setdefault(concept, []).append(f)

        any_resolved_this_round = False
        for concept, flags in by_concept.items():
            result = schema_discovery.reexamine_concept(tenant_id, concept)
            if result["resolved"]:
                resolved_log.append({"concept": concept, **result})
                any_resolved_this_round = True
            else:
                # Only carry into the next iteration if there IS a next
                # iteration -- otherwise record as an unresolved gap now.
                if iteration == MAX_ITERATIONS:
                    for f in flags:
                        unresolved_log.append(f)
                else:
                    outstanding_flags.extend(flags)

        if not any_resolved_this_round:
            # Nothing changed this round -- further iterations won't help,
            # so stop early and record whatever's left as unresolved.
            for concept, flags in by_concept.items():
                if concept not in [r["concept"] for r in resolved_log]:
                    unresolved_log.extend(flags)
            break

    for f in unresolved_log:
        db.record_schema_gap(
            tenant_id, f.get("concept"), f.get("flag_type", "missing_concept"),
            f.get("detail", ""), [f.get("_customer_id")] if f.get("_customer_id") else [],
        )

    if resolved_log:
        # Schema changed (new concept mappings) -- force Stage 2 to recompile
        # so the cached prompt_spec reflects what Stage 3 just fixed.
        prompt_architect.compile_if_stale(tenant_id, force=True)

    log.info("Stage 3 tenant '%s' complete: %d concept(s) resolved, %d gap(s) recorded.",
              tenant_id, len(resolved_log), len(unresolved_log))
    return {"ran": True, "sample_size": len(sample_ids), "resolved": resolved_log, "unresolved": unresolved_log}
