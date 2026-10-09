"""
One-time migration: converts existing seeded tenants (acme/globex/initech/
clean), currently living in the old fixed tables (customers/usage_metrics/
support_tickets/product_catalog), into the new schema-free model
(tenant_datasets/tenant_schema_columns/tenant_records).

Since we wrote these tenants' fixture data ourselves, we already know the
concept each fixed field maps to -- so this backfills `concept` tags
directly rather than re-running the Schema Discovery LLM call on data we
already fully understand. Real new tenant uploads go through
app.schema_discovery.ingest_file() instead, which infers everything from
content.

Usage:
    python scripts/migrate_to_schema_free.py [tenant_id ...]
    (no args = migrate every tenant returned by db.list_tenants())

Safe to re-run: it wipes and rewrites (via replace_tenant_schema_columns /
replace_tenant_records) rather than appending, so re-running just re-syncs
from the current fixed-table contents.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import db
from app.logging_config import get_logger

log = get_logger(__name__)

# Field -> concept, per dataset, using the same closed vocabulary as
# app.schema_discovery.CONCEPTS. This is exact because we control the
# fixture schema, not inferred.
FIELD_TO_CONCEPT = {
    "customers": {
        "customer_id": "customer_id", "customer_name": "customer_name",
        "plan_tier": "plan_tier", "seats": "seats", "renewal_date": "renewal_date",
    },
    "usage_metrics": {
        "customer_id": "customer_id", "active_users": "active_users",
        "storage_used_gb": "storage_used_gb", "storage_limit_gb": "storage_limit_gb",
        "feature_usage_score": "usage_trend_metric",
    },
    "support_tickets": {
        "customer_id": "customer_id", "category": "ticket_severity",
        "created_at": "ticket_created_at", "resolved": "ticket_resolved",
    },
    "product_catalog": {
        "product_id": "product_id", "product_name": "product_name",
        "price_per_seat": "price_per_seat", "tier_level": "product_tier_level",
    },
}

FIELD_DESCRIPTIONS = {
    "customer_id": "Unique identifier for the customer",
    "customer_name": "Customer / company name",
    "plan_tier": "Current subscription plan or tier",
    "seats": "Number of seats / licenses",
    "renewal_date": "Contract or subscription renewal date",
    "industry": "Customer's industry",
    "active_users": "Count of active users that month",
    "storage_used_gb": "Storage used, in GB",
    "storage_limit_gb": "Storage limit/quota, in GB",
    "feature_usage_score": "Aggregate feature usage score, derived from per-service usage",
    "month": "Month this usage snapshot covers",
    "ticket_id": "Unique identifier for the support ticket",
    "created_at": "Date the ticket was created",
    "category": "Ticket category, e.g. security/technical/billing",
    "subject": "Ticket subject / short description",
    "resolved": "Whether the ticket has been resolved",
    "product_id": "Unique identifier for the product",
    "product_name": "Product display name",
    "tier_level": "Numeric tier level (higher = more advanced plan)",
    "price_per_seat": "Price per seat, monthly",
    "complements": "Related/complementary product name(s)",
    "description": "Product description",
}

DTYPE_BY_FIELD_HINT = {
    "id": "identifier", "date": "date", "seats": "numeric", "score": "numeric",
    "gb": "numeric", "price": "numeric", "level": "numeric", "resolved": "boolean",
}


def _guess_dtype(field: str) -> str:
    for hint, dtype in DTYPE_BY_FIELD_HINT.items():
        if hint in field:
            return dtype
    return "categorical"


def _schema_version(fields: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(fields)).encode()).hexdigest()[:16]


def migrate_dataset(tenant_id: str, dataset_type: str, rows: list[dict], filename: str) -> None:
    if not rows:
        log.info("Tenant '%s': no rows for %s, skipping.", tenant_id, dataset_type)
        return

    fields = [f for f in rows[0].keys() if f not in ("extra_attributes",)]
    schema_version = _schema_version(fields)
    field_concepts = FIELD_TO_CONCEPT.get(dataset_type, {})
    join_key = "customer_id" if "customer_id" in fields else None

    dataset_id = db.upsert_tenant_dataset(
        tenant_id, dataset_type, filename, row_count=len(rows),
        join_key_column=join_key, schema_version=schema_version,
    )

    columns = []
    for field in fields:
        columns.append({
            "column": field,
            "inferred_label": field.replace("_", " ").title(),
            "description": FIELD_DESCRIPTIONS.get(field, f"{field} (migrated from fixed schema)"),
            "dtype": _guess_dtype(field),
            "semantic_role": "entity_id" if field == "customer_id" else (
                "join_key" if field == join_key else "metric" if _guess_dtype(field) == "numeric" else "dimension"
            ),
            "relevance": "high" if field in field_concepts else "medium",
            "concept": field_concepts.get(field),
            "stats": None,
        })
    # extra_attributes (dynamic fields already discovered previously) get
    # folded in too, so nothing tenant-specific is lost in migration.
    dynamic_fields = db.get_dynamic_fields(tenant_id, dataset_type) if hasattr(db, "get_dynamic_fields") else []
    for df_row in dynamic_fields:
        columns.append({
            "column": df_row["source_column"],
            "inferred_label": df_row["field_name"].replace("_", " ").title(),
            "description": df_row.get("description") or "Previously-discovered dynamic field.",
            "dtype": df_row.get("inferred_type") or "categorical",
            "semantic_role": df_row.get("semantic_role") or "dimension",
            "relevance": "medium",
            "concept": None,
            "stats": None,
        })

    db.replace_tenant_schema_columns(tenant_id, dataset_id, columns)

    records = []
    for row in rows:
        row_clean = dict(row)
        extra = row_clean.pop("extra_attributes", None)
        if extra:
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            row_clean.update(extra or {})
        entity_id = str(row_clean.get("customer_id")) if row_clean.get("customer_id") else None
        records.append({"entity_id": entity_id, "row": row_clean})
    db.replace_tenant_records(tenant_id, dataset_id, records)

    log.info("Migrated tenant '%s' dataset '%s': %d columns, %d rows.",
              tenant_id, dataset_type, len(columns), len(records))


def migrate_tenant(tenant_id: str) -> None:
    log.info("Migrating tenant '%s'...", tenant_id)
    migrate_dataset(tenant_id, "customers", db.get_customers(tenant_id), "customers.csv")

    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usage_metrics WHERE tenant_id = ?", (tenant_id,))
    usage_rows = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM support_tickets WHERE tenant_id = ?", (tenant_id,))
    ticket_rows = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM product_catalog WHERE tenant_id = ?", (tenant_id,))
    catalog_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    migrate_dataset(tenant_id, "usage_metrics", usage_rows, "usage_metrics.csv")
    migrate_dataset(tenant_id, "support_tickets", ticket_rows, "support_tickets.csv")
    migrate_dataset(tenant_id, "product_catalog", catalog_rows, "product_catalog.csv")
    log.info("Tenant '%s' migration complete.", tenant_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tenant_ids", nargs="*", help="Specific tenants to migrate (default: all)")
    args = parser.parse_args()

    db.init_db()
    tenant_ids = args.tenant_ids or [t["tenant_id"] for t in db.list_tenants()]
    if not tenant_ids:
        print("No tenants found -- nothing to migrate.")
        return

    for tenant_id in tenant_ids:
        migrate_tenant(tenant_id)
    print(f"Migrated {len(tenant_ids)} tenant(s): {', '.join(tenant_ids)}")


if __name__ == "__main__":
    main()
