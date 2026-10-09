"""
Data Ingestion — turns a raw file (CSV/Excel) into rows in the core tables
(customers, usage_metrics, support_tickets, product_catalog).

Not exposed over HTTP. Used as a library by whatever loader script you write
against the SQL database (data/generate_synthetic_data.py is one example);
column-name mapping (schema_mapping.py) and dynamic-column discovery are
available here for any loader that wants them.

Every core table is scoped by tenant_id as part of its primary key (see
data/schema.sql) -- ingest_file() requires tenant_id and every upsert_*
call in app/db.py is keyed on (tenant_id, ...), so ingesting one company's
file can never overwrite another company's rows even with identical
source IDs.
"""

import io

import pandas as pd

from app import db
from app.schema_mapping import get_column_mapping, apply_mapping, discover_unmapped_columns

# Columns each dataset must have, using our internal names, after any mapping
# has been applied. Anything else in the file is ignored.
REQUIRED_COLUMNS = {
    "customers": {"customer_id", "customer_name", "plan_tier", "seats", "renewal_date"},
    "usage_metrics": {"customer_id", "month", "active_users", "storage_used_gb",
                       "storage_limit_gb", "feature_usage_score"},
    "support_tickets": {"ticket_id", "customer_id", "created_at", "category", "subject", "resolved"},
    "product_catalog": {"product_id", "product_name", "tier_level", "price_per_seat"},
}

OPTIONAL_COLUMNS = {
    "customers": {"industry", "contract_start_date", "account_manager"},
    "usage_metrics": set(),
    "support_tickets": set(),
    "product_catalog": {"complements", "category", "description"},
}

DATASET_UPSERT_FN = {
    "customers": db.upsert_customers,
    "usage_metrics": db.upsert_usage_metrics,
    "support_tickets": db.upsert_support_tickets,
    "product_catalog": db.upsert_product_catalog,
}


class IngestionError(Exception):
    """Raised for any validation problem -- caught by main.py and turned into a 400."""


def read_uploaded_file(filename: str, raw_bytes: bytes) -> pd.DataFrame:
    lower = filename.lower()
    try:
        if lower.endswith(".csv"):
            return pd.read_csv(io.BytesIO(raw_bytes))
        elif lower.endswith((".xlsx", ".xls")):
            return pd.read_excel(io.BytesIO(raw_bytes))
    except Exception as e:
        raise IngestionError(f"Could not parse '{filename}': {e}")
    raise IngestionError(f"Unsupported file type for '{filename}' -- use .csv or .xlsx")


def _apply_mapping_if_present(tenant_id: str, dataset_type: str, df: pd.DataFrame) -> pd.DataFrame:
    """Applies this tenant's confirmed onboarding mapping for `dataset_type`,
    if one has been saved. All four dataset types go through this now --
    a tenant with source columns like 'Client_ID' or 'MRR_Seats_Active' in
    their usage_metrics/support_tickets/product_catalog files no longer has
    to pre-rename their own file to our exact internal names."""
    mapping = get_column_mapping(tenant_id, dataset_type)
    if mapping:
        df = apply_mapping(df, mapping)
    return df


def validate_columns(dataset_type: str, df: pd.DataFrame) -> None:
    required = REQUIRED_COLUMNS[dataset_type]
    missing = required - set(df.columns)
    if missing:
        raise IngestionError(
            f"'{dataset_type}' upload is missing required column(s): {sorted(missing)}. "
            f"Required: {sorted(required)}. Optional: {sorted(OPTIONAL_COLUMNS[dataset_type])}."
        )


def _clean_rows(dataset_type: str, df: pd.DataFrame) -> list[dict]:
    known_cols = REQUIRED_COLUMNS[dataset_type] | OPTIONAL_COLUMNS[dataset_type]
    keep_cols = [c for c in df.columns if c in known_cols]
    extra_cols = [c for c in df.columns if c not in known_cols]

    clean_df = df[keep_cols].where(pd.notnull(df[keep_cols]), None)

    # Normalize date-like and boolean columns to plain strings/ints SQLite expects.
    for date_col in ("renewal_date", "contract_start_date", "month", "created_at"):
        if date_col in clean_df.columns:
            clean_df[date_col] = pd.to_datetime(clean_df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    if "resolved" in clean_df.columns:
        clean_df["resolved"] = clean_df["resolved"].apply(
            lambda v: bool(v) if v is not None and str(v).strip() != "" else None
        )
    if "seats" in clean_df.columns:
        clean_df["seats"] = pd.to_numeric(clean_df["seats"], errors="coerce")

    rows = clean_df.to_dict(orient="records")

    # Anything not in our known schema no longer gets dropped -- it's kept
    # per-row under extra_attributes (see data/schema.sql) so it's never
    # lost, and app.schema_mapping.discover_unmapped_columns() can classify
    # the column itself (once) via app.db.dynamic_field_registry.
    if extra_cols:
        extras_df = df[extra_cols].where(pd.notnull(df[extra_cols]), None)
        extra_records = extras_df.to_dict(orient="records")
        for row, extra in zip(rows, extra_records):
            row["extra_attributes"] = {k: v for k, v in extra.items() if v is not None}

    return rows


def ingest_file(tenant_id: str, dataset_type: str, filename: str, raw_bytes: bytes) -> dict:
    """
    Full pipeline for one uploaded file: parse -> (map, for customers) ->
    validate -> clean -> upsert. Returns a small summary dict for the caller.
    """
    if dataset_type not in REQUIRED_COLUMNS:
        raise IngestionError(
            f"Unknown dataset_type '{dataset_type}'. Must be one of: {sorted(REQUIRED_COLUMNS)}"
        )

    df = read_uploaded_file(filename, raw_bytes)
    if df.empty:
        raise IngestionError(f"'{filename}' has no data rows.")

    df = _apply_mapping_if_present(tenant_id, dataset_type, df)

    validate_columns(dataset_type, df)
    rows = _clean_rows(dataset_type, df)

    # customers is the only dataset with a hard required-non-null check beyond
    # column presence -- a customer row without a renewal_date would silently
    # break the churn-window logic downstream.
    if dataset_type == "customers":
        bad = [r["customer_id"] for r in rows if not r.get("renewal_date") or not r.get("customer_id")]
        if bad:
            raise IngestionError(
                f"{len(bad)} customer row(s) have a missing/unparseable customer_id or renewal_date."
            )

    upsert_fn = DATASET_UPSERT_FN[dataset_type]
    count = upsert_fn(tenant_id, rows)

    # Auto-embed the catalog for vector-based product retrieval as soon as
    # it's ingested/updated, so the Recommendation Agent gets a real
    # narrowed shortlist instead of silently falling back to the full
    # catalog on every run (see app/agents/workflow.py's retrieval step).
    # Best-effort and non-blocking: if sentence-transformers isn't
    # installed, or embedding fails for any reason, ingestion must still
    # succeed -- vector search is an optional upgrade, not a hard
    # dependency (see app/vector_engine.py's module docstring).
    embedded_count = 0
    if dataset_type == "product_catalog":
        try:
            from app import vector_engine
            if vector_engine.is_available():
                full_catalog = db.get_product_catalog(tenant_id)
                embedded_count = vector_engine.embed_and_store_catalog(full_catalog, tenant_id)
        except Exception:
            # Never fail catalog ingestion because embedding hiccuped --
            # the pipeline still works via the full-catalog fallback in
            # workflow.py, just without narrowed candidates until this
            # is retried (e.g. by re-uploading, or POST /catalog/embed).
            pass

    # Discovery step: anything left over in extra_attributes gets classified
    # (once) so agents can pick it up at reasoning time. Never blocks or
    # fails ingestion -- this runs after the data is already safely stored.
    known_cols = REQUIRED_COLUMNS[dataset_type] | OPTIONAL_COLUMNS[dataset_type]
    sample_rows = rows[:5]
    discovered = []
    try:
        discovered = discover_unmapped_columns(
            tenant_id, dataset_type,
            sample_columns=list(df.columns),
            mapped_columns=known_cols,
            sample_rows=sample_rows,
        )
        for field in discovered:
            db.upsert_dynamic_field(**field)
    except Exception:
        # Discovery is best-effort metadata, not core data -- log and move on.
        pass

    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "dataset_type": dataset_type,
        "filename": filename,
        "rows_ingested": count,
        "new_fields_discovered": len(discovered),
        "products_embedded": embedded_count,
    }
