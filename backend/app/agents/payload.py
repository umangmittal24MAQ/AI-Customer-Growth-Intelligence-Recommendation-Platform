"""
Stage 4 of the schema-free pipeline (see schema_free_pipeline_design.md §4).

Builds the generic, tenant-agnostic payload shape agents should reason
over, sourced from the Stage 1/2 tables (tenant_datasets /
tenant_schema_columns / tenant_records) via app.db, instead of the fixed
`usage_rows` / `tickets` keys:

    {
      "customer_id": "...",
      "datasets": [
        {
          "dataset_label": "usage_metrics",
          "schema": [
            {"column": "...", "label": "...", "description": "...",
             "role": "...", "concept": "..." or None},
            ...
          ],
          "rows": [ {...}, ... ],
        },
        ...
      ],
    }

This is the *same* shape app.schema_self_correction._assemble_customer_payload
builds for the Stage-3 sample check, plus a `schema` block per dataset so an
agent reading this payload for the first time (no Stage-2 prompt_spec
priming) still knows what each raw column means -- Stage 3's check always
runs immediately after prompt_architect.compile_if_stale(), so it could get
away without repeating that context; a live per-customer agent call has no
such guarantee, so we include it here.

Datasets with no join_key_column (e.g. a product catalog) are tenant-wide,
not customer-specific, and are deliberately left OUT of this payload --
candidate products are already supplied separately (agents/workflow.py's
`candidate_products`), so duplicating the full catalog here would just be
noise/token cost with no new information.

Used by `is_schema_free_tenant()` / `build_generic_customer_payload()`
below; `pipeline.build_signal_request()` calls into this and merges the
result alongside the legacy fixed keys (customer_profile/usage_rows/
tickets) so both shapes are available to every agent during the Stage 4-6
transition -- see that function's docstring for why the merge, not a
straight replacement, is the safer rollout.
"""

from app import db


def is_schema_free_tenant(tenant_id: str) -> bool:
    """True if this tenant has any Stage-1-discovered datasets at all --
    covers both brand-new schema-free tenants and legacy tenants that have
    been run through scripts/migrate_to_schema_free.py."""
    return bool(db.list_tenant_datasets(tenant_id))


def _dataset_schema(tenant_id: str, dataset_id: int) -> list[dict]:
    columns = db.get_schema(tenant_id, dataset_id)
    return [
        {
            "column": c["column_name"],
            "label": c.get("inferred_label"),
            "description": c.get("description"),
            "role": c.get("semantic_role"),
            "concept": c.get("concept"),
        }
        for c in columns
    ]


def build_generic_customer_payload(tenant_id: str, entity_id: str) -> dict:
    """
    Generic, cross-dataset payload for one customer entity_id. Safe to call
    for any tenant -- returns {"customer_id": entity_id, "datasets": []} if
    the tenant has no Stage-1-discovered datasets (i.e. is not schema-free
    yet), which callers can treat the same as "nothing to add."
    """
    datasets = db.list_tenant_datasets(tenant_id)
    payload = {"customer_id": entity_id, "datasets": []}
    for d in datasets:
        join_key = d.get("join_key_column")
        if not join_key:
            # Tenant-wide dataset (e.g. product catalog) -- not customer
            # scoped, and already supplied to agents separately as
            # candidate_products. Skip here.
            continue
        rows = [
            r for r in db.get_dataset_rows(tenant_id, d["id"])
            if str(r.get(join_key, "")) == str(entity_id)
        ]
        if not rows:
            continue
        payload["datasets"].append({
            "dataset_label": d["dataset_label"],
            "schema": _dataset_schema(tenant_id, d["id"]),
            "rows": rows,
        })
    return payload


def missing_concepts_for_tenant(tenant_id: str) -> list[str]:
    """Concepts still flagged as unresolved data gaps (Stage 3) for this
    tenant -- handy context for an agent deciding whether to raise its own
    missing_concept flag, or for logging/telemetry. Not injected into the
    payload automatically since Stage 5 is what turns these into
    user-facing 'data_gaps' warnings; kept here as a small helper other
    callers (rule_engine, web_api) can reuse without re-querying db directly."""
    gaps = db.get_tenant_schema_gaps(tenant_id, unresolved_only=True)
    return sorted({g["concept"] for g in gaps if g.get("concept")})
