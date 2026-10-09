"""
Schema Discovery Agent (Stage 1 of the schema-free ingestion pipeline).
See schema_free_pipeline_design.md for the full design.

Replaces app.schema_mapping's fixed FIELD_DEFINITIONS/suggest_column_mapping
as the entry point for a newly uploaded tenant file. Instead of asking
"which of our fields does this match?", it asks the LLM to describe the
data on its own terms: a human-readable label, a description, a dtype, a
semantic role, a relevance guess, and -- only for the handful of concepts
plain-Python arithmetic still needs -- a `concept` tag.

Cheap fuzzy-matching against KNOWN_ALIASES (from schema_mapping.py) is kept
only as a seed hint fed into the LLM call, never as a gate.
"""

import hashlib
import json
from datetime import date

import pandas as pd
from app.indiaai_client import optional_client

from app.config import LLM_MODEL
from app.logging_config import get_logger
from app.schema_mapping import KNOWN_ALIASES
from app import db

log = get_logger(__name__)

# The one small closed vocabulary kept in the system -- not because we still
# believe in a fixed schema, but because a handful of deterministic
# calculations (churn trend %, MRR, bandwidth utilization) are plain
# arithmetic in Python and need to know *which specific column* to read.
# Everything else about the data is free-form. NULL/omitted concept is
# always valid -- most columns won't map to any of these.
CONCEPTS = [
    "customer_id", "customer_name", "renewal_date", "seats", "plan_tier",
    "active_users", "storage_used_gb", "storage_limit_gb", "usage_trend_metric",
    "ticket_severity", "ticket_created_at", "ticket_resolved", "product_id",
    "product_name", "price_per_seat", "product_tier_level",
]

SAMPLE_ROWS = 25


def _client() -> object | None:
    return optional_client()


def compute_column_stats(df: pd.DataFrame) -> dict:
    """Cheap pandas-computed stats per column -- dtype, null %, distinct
    count, min/max (numeric/date), sample values. Fed to the LLM as evidence
    so it isn't guessing purely from the column name."""
    stats = {}
    for col in df.columns:
        series = df[col]
        non_null = series.dropna()
        entry = {
            "pandas_dtype": str(series.dtype),
            "is_numeric": bool(pd.api.types.is_numeric_dtype(series)),
            "null_pct": round(100 * (1 - len(non_null) / len(series)), 1) if len(series) else 0,
            "distinct_count": int(non_null.nunique()),
            "sample_values": [str(v) for v in non_null.head(5).tolist()],
        }
        if pd.api.types.is_numeric_dtype(series):
            entry["min"] = float(non_null.min()) if len(non_null) else None
            entry["max"] = float(non_null.max()) if len(non_null) else None
        stats[col] = entry
    return stats


def compute_schema_version(columns: list[str], stats: dict) -> str:
    """Hash of columns + dtypes, used to detect 'this file changed' on
    re-upload so Stage 1/2 only re-run when something actually changed."""
    fingerprint = json.dumps(
        {c: stats.get(c, {}).get("pandas_dtype") for c in sorted(columns)},
        sort_keys=True,
    )
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


def _seed_hints(columns: list[str]) -> dict[str, str]:
    """Cheap fuzzy-matching against all known aliases across all legacy
    dataset types, purely as a seed hint fed into the LLM prompt -- never a
    gate, never used to bypass the LLM or force a rename."""
    from difflib import get_close_matches
    hints = {}
    all_candidates = {}  # candidate_name -> concept-ish label
    for dataset_type, alias_map in KNOWN_ALIASES.items():
        for field, aliases in alias_map.items():
            for a in [field] + aliases:
                all_candidates[a] = field
    normalized = {c.lower().replace(" ", "_"): c for c in columns}
    for norm_col, orig_col in normalized.items():
        if norm_col in all_candidates:
            hints[orig_col] = all_candidates[norm_col]
            continue
        match = get_close_matches(norm_col, all_candidates.keys(), n=1, cutoff=0.8)
        if match:
            hints[orig_col] = all_candidates[match[0]]
    return hints


def _fallback_dtype(col: str, stats: dict) -> str:
    """Best-effort dtype guess used only when the LLM call fails/no API
    key. Still conservative (a wrong guess here just means a Stage 3
    sample-check flag or a slightly-off adapter heuristic downstream, not
    a crash) -- this replaces the old binary numeric/categorical-only
    split, which mis-set every plain string column to "numeric" whenever
    pandas' `str(series.dtype)` printed something other than the literal
    "object" (e.g. pandas' newer string dtype prints as "str")."""
    if stats.get("is_numeric"):
        return "numeric"
    samples = stats.get("sample_values") or []
    if samples:
        parsed = sum(1 for s in samples if _looks_like_date(s))
        if parsed >= max(1, len(samples) - 1):  # allow one odd/short sample
            return "date"
    name = col.lower()
    distinct = stats.get("distinct_count") or 0
    avg_len = (sum(len(str(s)) for s in samples) / len(samples)) if samples else 0
    if name.endswith("_id") or name == "id" or (distinct and stats.get("null_pct", 0) == 0 and avg_len <= 20 and "id" in name):
        return "identifier"
    if avg_len > 30:
        return "free_text"
    return "categorical"


def _looks_like_date(value) -> bool:
    try:
        date.fromisoformat(str(value)[:10])
        return True
    except ValueError:
        return False


def _fallback_column_entry(col: str, stats: dict) -> dict:
    """Used only if the LLM call fails/no API key -- never blocks ingestion.
    Conservative: unknown semantic role, low relevance, no concept, so the row
    still gets stored (raw values preserved in tenant_records) and can be
    reclassified later once the LLM path is available."""
    return {
        "column": col,
        "inferred_label": col.replace("_", " ").title(),
        "description": "Not yet classified (LLM unavailable at discovery time).",
        "dtype": _fallback_dtype(col, stats),
        "semantic_role": "dimension",
        "relevance": "unknown",
        "concept": None,
    }


# Exact, trusted field aliases for bundled demo datasets. Unknown fields
# remain unclassified so their meaning is never silently fabricated.
FALLBACK_CONCEPT_COLUMNS = {
 "customer_id": {"customer_id", "seller_id", "workspace_id", "plant_code", "store_id", "account_ref"},
 "customer_name": {"customer_name", "store_name", "customer_org", "facility_name", "retailer_name", "company_name"},
 "plan_tier": {"plan_tier", "subscription_tier", "service_plan", "package_tier", "plan_level"},
 "seats": {"seats", "licensed_seats", "machine_count", "pos_terminals", "seat_licenses"},
 "renewal_date": {"renewal_date", "renews_on", "contract_expiry", "agreement_end_date"},
 "active_users": {"active_users", "monthly_active_devs", "active_machines_operating", "active_terminals_in_use", "active_reps_logged_in"},
 "storage_used_gb": {"storage_used_gb", "data_stored_gb"},
 "storage_limit_gb": {"storage_limit_gb", "storage_plan_cap_gb"},
 "usage_trend_metric": {"feature_usage_score", "product_engagement_index", "equipment_uptime_pct", "foot_traffic_index", "crm_adoption_score", "monthly_gmv_usd"},
 "ticket_severity": {"severity"},
 "ticket_created_at": {"created_at", "opened_date", "opened_on", "logged_on", "filed_on", "created_on"},
 "ticket_resolved": {"resolved", "is_closed", "closed_flag", "status_closed"},
 "product_id": {"product_id", "sku"},
 "product_name": {"product_name", "offering_name"},
 "price_per_seat": {"price_per_seat", "seat_price_usd"},
 "product_tier_level": {"tier_level", "tier"},
}

def _fallback_schema(columns: list[str], stats: dict, dataset_label: str, version: str) -> dict:
    entries = []
    join = None
    for column in columns:
        normalized = column.strip().lower().replace(" ", "_")
        entry = _fallback_column_entry(column, stats[column])
        concept = next((c for c, aliases in FALLBACK_CONCEPT_COLUMNS.items() if normalized in aliases), None)
        if concept:
            entry["concept"] = concept
            entry["relevance"] = "high"
            entry["semantic_role"] = "entity_id" if concept == "customer_id" else "metric"
            if concept == "customer_id":
                join = column
        entry["stats"] = stats[column]
        entries.append(entry)
    return {"dataset_label": dataset_label or "unclassified_dataset", "join_key_column": join,
            "columns": entries, "schema_version": version}

def discover_schema(df: pd.DataFrame, dataset_label_hint: str = None) -> dict:
    """
    Runs Stage 1 for one uploaded file.

    Returns:
        {
          "dataset_label": "...",         # content-based classification, not filename-based
          "join_key_column": "..." | None,
          "columns": [ {column, inferred_label, description, dtype,
                        semantic_role, relevance, concept, stats}, ... ],
          "schema_version": "...",
        }
    """
    columns = list(df.columns)
    stats = compute_column_stats(df)
    schema_version = compute_schema_version(columns, stats)
    seed_hints = _seed_hints(columns)
    sample_rows = df.head(SAMPLE_ROWS).fillna("").to_dict(orient="records")

    # Bundled Traject demo schemas are deterministic and already known: do not
    # spend an LLM request rediscovering their exact, reviewed field mappings.
    trusted_showcase_columns = {
        "workspace_id", "customer_org", "subscription_tier", "licensed_seats",
        "renews_on", "csm_owner", "nps_last_survey", "usage_month",
        "product_engagement_index", "monthly_active_devs", "data_stored_gb",
        "storage_plan_cap_gb", "api_calls", "issue_category", "summary",
        "opened_on", "is_closed", "sku", "offering_name", "tier",
        "seat_price_usd", "product_group",
    }
    if columns and set(columns).issubset(trusted_showcase_columns) and             ("workspace_id" in columns or "sku" in columns):
        return _fallback_schema(columns, stats, dataset_label_hint, schema_version)
    client = _client()
    if client is None:
        log.warning("No IndiaAI key -- using conservative fallback classification for all columns.")
        return _fallback_schema(columns, stats, dataset_label_hint, schema_version)

    prompt = f"""You are classifying an uploaded tenant data file for a B2B SaaS upsell/churn analysis tool.
Describe the data on its own terms -- do not assume it matches any predefined schema.

Filename hint: {dataset_label_hint or "unknown"}
Columns and stats: {json.dumps(stats, indent=2)}
Sample rows (up to {SAMPLE_ROWS}): {json.dumps(sample_rows, indent=2, default=str)}
Seed hints from fuzzy alias matching (treat as hints only, not ground truth): {json.dumps(seed_hints)}

For EACH column, return an object with:
  - "column": exact column name as given
  - "inferred_label": short human-readable name
  - "description": one sentence describing what this column represents
  - "dtype": one of identifier | numeric | categorical | date | boolean | free_text
  - "semantic_role": one of entity_id | join_key | metric | dimension | narrative | noise
  - "relevance": one of high | medium | low | unknown
  - "concept": one of {json.dumps(CONCEPTS)}, or null if none apply

Also decide, at the dataset level:
  - "dataset_label": what kind of dataset is this overall (e.g. "customers", "usage_metrics",
    "support_tickets", "product_catalog", or something else entirely like "nps_survey", "billing_export")
  - "join_key_column": which column (exact name) joins this dataset back to a customer entity, or null

Return ONLY a JSON object: {{"dataset_label": ..., "join_key_column": ..., "columns": [...]}}
No preamble, no markdown fences."""

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        col_by_name = {c["column"]: c for c in result.get("columns", [])}
        # Ensure every actual column got classified even if the LLM skipped one.
        final_columns = []
        for c in columns:
            entry = col_by_name.get(c) or _fallback_column_entry(c, stats[c])
            entry["stats"] = stats[c]
            if entry.get("concept") not in CONCEPTS:
                entry["concept"] = None
            final_columns.append(entry)
        return {
            "dataset_label": result.get("dataset_label") or dataset_label_hint or "unclassified_dataset",
            "join_key_column": result.get("join_key_column"),
            "columns": final_columns,
            "schema_version": schema_version,
        }
    except Exception as e:
        log.warning("Schema Discovery LLM call failed (%s) -- using conservative fallback.", e)
        return _fallback_schema(columns, stats, dataset_label_hint, schema_version)


def reexamine_concept(tenant_id: str, concept: str) -> dict:
    """
    Stage 3 callback: given a concept the sample-run Signal Agent flagged as
    missing/low-confidence, re-examine this tenant's already-discovered
    columns (across ALL their datasets) for anything that could map to it --
    Stage 1 runs per-file and can miss a cross-dataset fit, or under-weight
    a column's relevance on first pass. Never re-reads raw files; works off
    the existing tenant_schema_columns catalog only.

    Returns {"resolved": bool, "dataset_id": int|None, "column_name": str|None,
              "detail": str} -- if resolved, the caller should update that
    column's `concept` field via app.db (done here directly for convenience).
    """
    if concept not in CONCEPTS:
        return {"resolved": False, "dataset_id": None, "column_name": None,
                "detail": f"'{concept}' is not a recognized concept."}

    catalog = db.get_tenant_schema_catalog(tenant_id)
    if not catalog:
        return {"resolved": False, "dataset_id": None, "column_name": None,
                "detail": "No schema catalog found for this tenant."}

    already_mapped = next((c for c in catalog if c["concept"] == concept), None)
    if already_mapped:
        return {"resolved": True, "dataset_id": already_mapped["dataset_id"],
                "column_name": already_mapped["column_name"],
                "detail": "Already mapped -- no re-examination needed."}

    client = _client()
    if client is None:
        return {"resolved": False, "dataset_id": None, "column_name": None,
                "detail": "LLM unavailable -- cannot re-examine, recording as unresolved gap."}

    slim = [
        {"dataset": c["dataset_label"], "column": c["column_name"],
         "description": c["description"], "dtype": c["dtype"], "concept": c["concept"]}
        for c in catalog
    ]
    prompt = f"""A downstream reasoning agent flagged that it could not find data for the concept
"{concept}" while analyzing this tenant. Re-examine the tenant's FULL column catalog below -- across
all their uploaded datasets -- and decide if any column, previously left unmapped or mapped to a
different concept, could genuinely represent "{concept}".

Column catalog: {json.dumps(slim, indent=2)}

Return ONLY a JSON object: {{"found": true|false, "dataset": "...", "column": "...", "reason": "..."}}
If found is false, dataset/column should be null. Be conservative -- only say found:true if a column
plausibly represents this concept, not just because nothing else fits. No preamble, no markdown fences."""

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL, temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        if result.get("found") and result.get("column"):
            match = next((c for c in catalog if c["column_name"] == result["column"]
                          and c["dataset_label"] == result.get("dataset")), None) or \
                    next((c for c in catalog if c["column_name"] == result["column"]), None)
            if match:
                db.set_column_concept(tenant_id, match["dataset_id"], match["column_name"], concept)
                return {"resolved": True, "dataset_id": match["dataset_id"],
                        "column_name": match["column_name"], "detail": result.get("reason", "")}
        return {"resolved": False, "dataset_id": None, "column_name": None,
                "detail": result.get("reason", "Confirmed absent after re-examination.")}
    except Exception as e:
        log.warning("reexamine_concept LLM call failed for tenant '%s', concept '%s' (%s).",
                    tenant_id, concept, e)
        return {"resolved": False, "dataset_id": None, "column_name": None,
                "detail": f"Re-examination call failed: {e}"}


def ingest_file(tenant_id: str, filepath: str, original_filename: str, dataset_label_hint: str = None) -> dict:
    """
    Full Stage-1 ingestion for one file: read it, discover its schema (only
    if the schema_version changed since last time -- cheap re-upload
    protection), persist tenant_datasets/tenant_schema_columns, and store
    every row as JSON in tenant_records, resolved against the discovered
    join key if one was found.
    """
    if filepath.endswith(".csv"):
        df = pd.read_csv(filepath)
    else:
        df = pd.read_excel(filepath)

    existing = db.get_tenant_dataset(tenant_id, original_filename)
    discovery = discover_schema(df, dataset_label_hint or original_filename)

    if existing and existing.get("schema_version") == discovery["schema_version"]:
        log.info("Dataset '%s' for tenant '%s' unchanged -- skipping re-discovery.",
                  original_filename, tenant_id)
        dataset_id = existing["id"]
    else:
        dataset_id = db.upsert_tenant_dataset(
            tenant_id, discovery["dataset_label"], original_filename,
            row_count=len(df), join_key_column=discovery["join_key_column"],
            schema_version=discovery["schema_version"],
        )
        db.replace_tenant_schema_columns(tenant_id, dataset_id, discovery["columns"])

        join_key = discovery["join_key_column"]
        records = []
        for row in df.fillna("").to_dict(orient="records"):
            entity_id = str(row.get(join_key)) if join_key and join_key in row and row.get(join_key) != "" else None
            records.append({"entity_id": entity_id, "row": row})
        db.replace_tenant_records(tenant_id, dataset_id, records)
        log.info("Discovered schema for '%s' (tenant '%s'): dataset_label=%s, %d columns, %d rows.",
                  original_filename, tenant_id, discovery["dataset_label"], len(discovery["columns"]), len(df))

    return {"dataset_id": dataset_id, **discovery, "changed": not existing or existing.get("schema_version") != discovery["schema_version"]}
