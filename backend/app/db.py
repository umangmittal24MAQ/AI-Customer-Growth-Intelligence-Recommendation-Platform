"""
All database read/write functions live here. Nothing else in the app
should touch sqlite3 directly — keeps the DB layer swappable
(e.g. SQLite -> PostgreSQL later) without touching business logic.

MULTI-TENANCY: every function that touches customers/usage_metrics/
service_usage/support_tickets/product_catalog/product_embeddings/
transactions/recommendations_log now takes tenant_id as a REQUIRED first
argument. There is no "give me everyone" query left in this file for those
tables on purpose -- a caller that forgets to scope by tenant should get a
TypeError, not silently-wrong cross-tenant data.
"""

import json
import os
import shutil
import sqlite3
import time
from datetime import date, datetime, timedelta
from app.config import DB_PATH

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "schema.sql")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """
    Creates every table the app needs if it doesn't already exist, and
    creates the DB file itself if it doesn't exist yet.

    v1 -> v2 migration note: v1's core tables (customers, usage_metrics,
    support_tickets, product_catalog, ...) had NO tenant_id column at all,
    so every tenant's data lived in one shared table and re-ingesting a
    different tenant with overlapping source IDs (e.g. "CUST-001") could
    silently overwrite another tenant's row. There is no safe automatic
    migration path for that -- we can't tell which tenant an old row
    actually belonged to once it may have already been overwritten. So: if
    an old-schema DB is detected, it's renamed aside (never deleted) and a
    fresh v2 database is created. Re-ingest each tenant's data after this
    runs once.
    """
    db_dir = os.path.dirname(os.path.abspath(DB_PATH))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customers'")
            has_customers = cur.fetchone() is not None
            is_old_schema = False
            if has_customers:
                cur.execute("PRAGMA table_info(customers)")
                cols = {row[1] for row in cur.fetchall()}
                is_old_schema = "tenant_id" not in cols
        finally:
            conn.close()
        if is_old_schema:
            backup_path = f"{DB_PATH}.pre-tenant-migration.{int(time.time())}.bak"
            shutil.move(DB_PATH, backup_path)

    with open(SCHEMA_PATH, "r") as f:
        schema_sql = f.read()
    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()

        # Lightweight migrations for DBs already on the v2 (tenant-scoped)
        # schema but created before a later column was added.
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(tenant_profiles)")
        existing_cols = {row[1] for row in cur.fetchall()}
        if "total_customers" not in existing_cols:
            cur.execute("ALTER TABLE tenant_profiles ADD COLUMN total_customers INTEGER")
            conn.commit()

        for table in ("customers", "usage_metrics", "support_tickets", "product_catalog"):
            cur.execute(f"PRAGMA table_info({table})")
            cols = {row[1] for row in cur.fetchall()}
            if "extra_attributes" not in cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN extra_attributes JSON")
        conn.commit()

        cur.execute("PRAGMA table_info(recommendations_log)")
        rec_cols = {row[1] for row in cur.fetchall()}
        if "no_recommendation_reason_code" not in rec_cols:
            cur.execute("ALTER TABLE recommendations_log ADD COLUMN no_recommendation_reason_code TEXT DEFAULT NULL")
            conn.commit()
        if "confidence" not in rec_cols:
            # 0-1 confidence, added after revenue_score. Rows logged before
            # this column existed stay NULL until re-analyzed; readers
            # (web_api._stored_confidence) fall back to a revenue_score-derived
            # estimate for those, and get_latest_recommendations sorts NULLs
            # last so they don't top the confidence-ranked list.
            cur.execute("ALTER TABLE recommendations_log ADD COLUMN confidence REAL DEFAULT NULL")
            conn.commit()
        if "retention_action" not in rec_cols:
            # JSON-encoded RetentionAction dict (action_type, action_text,
            # talking_point) from the Retention agent -- the concrete "what
            # to do instead" for a customer with no upsell this cycle. NULL
            # for rows logged before this agent existed, and for rows that
            # do have a confident recommended_product (reason_code is NULL).
            cur.execute("ALTER TABLE recommendations_log ADD COLUMN retention_action TEXT DEFAULT NULL")
            conn.commit()

        cur.execute("PRAGMA table_info(product_catalog)")
        catalog_cols = {row[1] for row in cur.fetchall()}
        if "source" not in catalog_cols:
            # Existing rows predate this column and were, in practice, all
            # written by the demo auto-seed fallback (app/onboarding.py) or
            # scripts/generate_dynamic_fields_report.py-style manual seeding --
            # real per-tenant uploads go through data_ingestion.py, which now
            # tags 'upload' explicitly going forward. Backfill existing rows
            # as 'demo_seed' (the more conservative assumption) so tenants who
            # never actually uploaded their own catalog start showing the gap
            # warning instead of silently looking fully set up.
            cur.execute("ALTER TABLE product_catalog ADD COLUMN source TEXT DEFAULT 'upload'")
            cur.execute("UPDATE product_catalog SET source = 'demo_seed'")
            conn.commit()

        cur.execute("PRAGMA table_info(tenant_config)")
        config_cols = {row[1] for row in cur.fetchall()}
        if "revenue_model" not in config_cols:
            # "recurring" (SaaS-style, price_per_seat is a monthly rate --
            # multiplying by seats is a valid "/mo potential" figure) vs.
            # "one_time" (retail/goods -- price_per_seat is a per-unit price,
            # so "/mo" on the eligible-revenue total would be fabricated).
            # Default to 'recurring' for existing tenants (all pre-dated this
            # column and were SaaS demo tenants); new tenants should set this
            # explicitly via POST /tenant/{id}/config during onboarding.
            cur.execute("ALTER TABLE tenant_config ADD COLUMN revenue_model TEXT DEFAULT 'recurring'")
            conn.commit()

        # chat_sessions persistence
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_sessions'")
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE chat_sessions (
                    conversation_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    history JSON NOT NULL DEFAULT '[]',
                    first_message TEXT,
                    last_customer_id TEXT,
                    last_customer_name TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Chat session persistence
# ---------------------------------------------------------------------------
def save_chat_session(session: dict) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO chat_sessions
               (conversation_id, tenant_id, history, first_message,
                last_customer_id, last_customer_name, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(conversation_id) DO UPDATE SET
               history = excluded.history,
               first_message = COALESCE(excluded.first_message, chat_sessions.first_message),
               last_customer_id = excluded.last_customer_id,
               last_customer_name = excluded.last_customer_name,
               updated_at = datetime('now')""",
        (
            session["conversation_id"],
            session["tenant_id"],
            json.dumps(session.get("history", [])),
            session.get("first_message"),
            session.get("last_customer_id"),
            session.get("last_customer_name"),
            session.get("created_at"),
        ),
    )
    conn.commit()
    conn.close()


def load_chat_session(conversation_id: str, tenant_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE conversation_id = ? AND tenant_id = ?",
        (conversation_id, tenant_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "conversation_id": row["conversation_id"],
        "tenant_id": row["tenant_id"],
        "history": json.loads(row["history"] or "[]"),
        "first_message": row["first_message"],
        "last_customer_id": row["last_customer_id"],
        "last_customer_name": row["last_customer_name"],
        "created_at": row["created_at"],
    }


def list_chat_sessions_db(tenant_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT conversation_id, first_message, last_customer_name, created_at, updated_at, history FROM chat_sessions WHERE tenant_id = ? ORDER BY updated_at DESC LIMIT 50",
        (tenant_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        history = json.loads(row["history"] or "[]")
        result.append({
            "conversation_id": row["conversation_id"],
            "first_message": row["first_message"],
            "last_customer": row["last_customer_name"],
            "created_at": row["created_at"],
            "turns": len(history) // 2,
        })
    return result


def delete_chat_session_db(conversation_id: str, tenant_id: str) -> bool:
    conn = get_connection()
    cur = conn.execute(
        "DELETE FROM chat_sessions WHERE conversation_id = ? AND tenant_id = ?",
        (conversation_id, tenant_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0
# Tenant authorization (app/auth.py)
# ---------------------------------------------------------------------------
def upsert_tenant_api_key(tenant_id: str, api_key_hash: str, company_name: str = None) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tenant_api_keys (tenant_id, api_key_hash, company_name, created_at, revoked)
           VALUES (?, ?, ?, datetime('now'), 0)
           ON CONFLICT(tenant_id) DO UPDATE SET
             api_key_hash = excluded.api_key_hash,
             company_name = COALESCE(excluded.company_name, tenant_api_keys.company_name),
             revoked = 0""",
        (tenant_id, api_key_hash, company_name),
    )
    conn.commit()
    conn.close()


def get_tenant_api_key(tenant_id: str) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tenant_api_keys WHERE tenant_id = ?", (tenant_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def revoke_tenant_api_key(tenant_id: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tenant_api_keys SET revoked = 1 WHERE tenant_id = ?", (tenant_id,))
    conn.commit()
    conn.close()


def create_tenant_account(tenant_id: str, client_name: str, email: str, password_hash: str) -> None:
    """Raises sqlite3.IntegrityError if tenant_id or email already exists --
    callers (app/accounts.py) check email uniqueness themselves first for a
    clean error message, but this is the actual constraint enforcement."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tenant_accounts (tenant_id, client_name, email, password_hash, created_at)
           VALUES (?, ?, ?, ?, datetime('now'))""",
        (tenant_id, client_name, email, password_hash),
    )
    conn.commit()
    conn.close()


def get_account_by_email(email: str) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tenant_accounts WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_account_by_tenant_id(tenant_id: str) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tenant_accounts WHERE tenant_id = ?", (tenant_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def list_tenants() -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT tenant_id, company_name, created_at, revoked FROM tenant_api_keys")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
def get_customers(tenant_id: str, customer_ids: list[str] = None) -> list[dict]:
    """
    Adapter (schema_free_pipeline_design.md gap fix): the legacy `customers`
    table is what every downstream consumer (web_api.py's list/detail/_mrr/
    _churn/_bandwidth, rule_engine.py, pipeline.py) reads a "customer" dict
    from. Stage 1-3 ingestion for a genuinely new schema-free tenant never
    writes to this table -- it only writes tenant_datasets/
    tenant_schema_columns/tenant_records -- so a brand-new schema-free
    tenant previously got an empty customer list and a 404 on every detail
    page, with no crash to signal why.

    Fix: if the legacy table has no rows for this tenant, and the tenant
    has Stage-1-discovered data at all, synthesize customer dicts from
    tenant_records via resolve_concept() instead of returning empty. This
    keeps every downstream consumer working unchanged against the same
    dict shape they already expect, rather than requiring each of them
    (rule_engine.py, web_api._churn/_mrr/_bandwidth) to be individually
    rewritten to know about tenant_records -- the normalization happens
    once, here, at the data-access boundary.

    Fields with no mapped concept get a safe, clearly-fallback default
    (e.g. a far-future renewal_date) so nothing downstream crashes on a
    None it doesn't null-check -- this is a legacy-compatibility shim, not
    a claim of accuracy. app/insights.py's core-insight gap reporting is
    independent of this (it calls resolve_concept itself) and will still
    honestly report "insufficient data" for whichever concepts are
    actually missing, regardless of the defaults used here.
    """
    conn = get_connection()
    cur = conn.cursor()
    if customer_ids:
        placeholders = ",".join("?" for _ in customer_ids)
        cur.execute(
            f"SELECT * FROM customers WHERE tenant_id = ? AND customer_id IN ({placeholders})",
            [tenant_id, *customer_ids],
        )
    else:
        cur.execute("SELECT * FROM customers WHERE tenant_id = ?", (tenant_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["renewal_date"] = date.fromisoformat(r["renewal_date"])
        r["extra_attributes"] = json.loads(r["extra_attributes"]) if r.get("extra_attributes") else {}

    if rows:
        return rows

    if not list_tenant_datasets(tenant_id):
        return []  # not a schema-free tenant either -- genuinely no data yet

    return [
        _build_synthetic_customer(tenant_id, entity_id, concept_cache={})
        for entity_id in _schema_free_customer_ids(tenant_id, customer_ids)
    ]


def _schema_free_customer_ids(tenant_id: str, customer_ids: list[str] = None) -> list[str]:
    conn = get_connection()
    cur = conn.cursor()
    if customer_ids:
        placeholders = ",".join("?" for _ in customer_ids)
        cur.execute(
            f"SELECT DISTINCT entity_id FROM tenant_records "
            f"WHERE tenant_id = ? AND entity_id IN ({placeholders})",
            [tenant_id, *customer_ids],
        )
    else:
        cur.execute(
            "SELECT DISTINCT entity_id FROM tenant_records WHERE tenant_id = ? AND entity_id IS NOT NULL",
            (tenant_id,),
        )
    ids = [r[0] for r in cur.fetchall() if r[0]]
    conn.close()
    return ids


def _resolve_customer_field(tenant_id: str, entity_id: str, concept: str, concept_cache: dict):
    """Looks up whichever column maps to `concept` for this tenant (cached
    per get_customers() call so a multi-customer list doesn't re-query
    tenant_schema_columns once per customer per field), then reads that
    column's value for this one entity_id. Returns None if the concept has
    no mapped column, or the row for this entity doesn't have it."""
    if concept not in concept_cache:
        concept_cache[concept] = resolve_concept(tenant_id, concept)
    mapping = concept_cache[concept]
    if not mapping:
        return None
    matching_rows = get_dataset_rows(tenant_id, mapping["dataset_id"], entity_id=entity_id)
    if not matching_rows:
        return None
    return matching_rows[0].get(mapping["column_name"])


def _build_synthetic_customer(tenant_id: str, entity_id: str, concept_cache: dict) -> dict:
    name = _resolve_customer_field(tenant_id, entity_id, "customer_name", concept_cache)
    industry = _resolve_customer_field(tenant_id, entity_id, "industry", concept_cache)
    
    if industry is None:
        dataset = _tenant_dataset_by_concepts(tenant_id, "customer_name") or _tenant_dataset_by_label(tenant_id, "customer", "seller")
        if dataset:
            rows = get_dataset_rows(tenant_id, dataset["id"], entity_id=entity_id)
            if rows:
                industry = rows[0].get("industry")

    plan_tier = _resolve_customer_field(tenant_id, entity_id, "plan_tier", concept_cache)
    seats = _resolve_customer_field(tenant_id, entity_id, "seats", concept_cache)
    account_manager = _resolve_customer_field(tenant_id, entity_id, "account_manager", concept_cache)
    renewal_raw = _resolve_customer_field(tenant_id, entity_id, "renewal_date", concept_cache)
    current_product = _resolve_customer_field(tenant_id, entity_id, "product_name", concept_cache)

    renewal_date = None
    if renewal_raw:
        try:
            renewal_date = date.fromisoformat(str(renewal_raw)[:10])
        except ValueError:
            renewal_date = None

    return {
        "tenant_id": tenant_id,
        "customer_id": entity_id,
        "customer_name": name or entity_id,
        "industry": industry or "Unknown",
        "plan_tier": plan_tier or "Unknown",
        "current_product": current_product,
        "seats": seats if seats is not None else 0,
        # Legacy-compatibility fallback only, per this function's docstring --
        # not an inferred value. A missing renewal_date concept is still
        # reported truthfully by app/insights.py's own resolve_concept check.
        "renewal_date": renewal_date or (date.today() + timedelta(days=365)),
        "account_manager": account_manager or "Unassigned",
        "extra_attributes": {},
        "is_schema_free_synthetic": True,
    }


def get_usage(tenant_id: str, customer_id: str) -> list[dict]:
    """
    Adapter, same rationale as get_customers() above: the legacy
    `usage_metrics` table is never populated by Stage 1-3 ingestion for a
    genuinely new schema-free tenant, so this used to return [] even when
    the tenant's real usage data is sitting in tenant_records. Falls back
    to `_schema_free_usage_rows()` when the legacy table has nothing for
    this tenant.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM usage_metrics WHERE tenant_id = ? AND customer_id = ? ORDER BY month ASC",
        (tenant_id, customer_id),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["extra_attributes"] = json.loads(r["extra_attributes"]) if r.get("extra_attributes") else {}

    if rows:
        return rows

    if not list_tenant_datasets(tenant_id):
        return []

    return _schema_free_usage_rows(tenant_id, customer_id)


def _tenant_dataset_by_label(tenant_id: str, *label_keywords: str) -> dict | None:
    """First of this tenant's Stage-1-discovered datasets whose
    dataset_label contains any of `label_keywords` (case-insensitive) --
    e.g. _tenant_dataset_by_label(t, "usage") matches a dataset labeled
    "usage_metrics" or "usage". Returns None if nothing matches, which
    callers treat as "this tenant never uploaded that kind of data".

    Kept only as a fallback behind _tenant_dataset_by_concepts() below --
    the Stage-2/Stage-1 dataset_label is free text the LLM chooses per
    tenant's own vocabulary (a retail tenant's usage-equivalent dataset
    might get labeled "sales_performance_metrics", a manufacturing
    tenant's "equipment_metrics"), so keyword-matching it is inherently
    tenant/industry-specific and silently misses those cases."""
    for d in list_tenant_datasets(tenant_id):
        label = (d.get("dataset_label") or "").lower()
        if any(kw in label for kw in label_keywords):
            return d
    return None


def _tenant_dataset_by_concepts(tenant_id: str, *concepts: str) -> dict | None:
    """Dataset containing the most columns resolved to any of `concepts`
    (schema_discovery.py's closed concept vocabulary) -- this is the
    content-based way to find "this tenant's usage dataset" /
    "...ticket dataset" / "...catalog dataset" regardless of what the LLM
    happened to name it, which the design doc's whole premise is that we
    shouldn't assume a schema/label at all. Returns None if no column
    anywhere for this tenant resolved to any of these concepts."""
    if not concepts:
        return None
    conn = get_connection()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in concepts)
    cur.execute(
        f"""SELECT dataset_id, COUNT(*) AS n FROM tenant_schema_columns
            WHERE tenant_id = ? AND concept IN ({placeholders})
            GROUP BY dataset_id ORDER BY n DESC LIMIT 1""",
        (tenant_id, *concepts),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    dataset_id = row["dataset_id"]
    cur.execute("SELECT * FROM tenant_datasets WHERE tenant_id = ? AND id = ?", (tenant_id, dataset_id))
    d = cur.fetchone()
    conn.close()
    return dict(d) if d else None


# Concept groups used to content-match a tenant's usage/ticket/catalog
# dataset -- kept here so schema_discovery.CONCEPTS stays the single source
# of truth for the vocabulary itself, this just groups it by "which legacy
# adapter shape does this concept feed".
_USAGE_CONCEPTS = ("active_users", "storage_used_gb", "storage_limit_gb", "usage_trend_metric")
_TICKET_CONCEPTS = ("ticket_severity", "ticket_created_at", "ticket_resolved")
_CATALOG_CONCEPTS = ("product_id", "product_name", "price_per_seat", "product_tier_level")


def _find_tenant_dataset(tenant_id: str, concepts: tuple[str, ...], *label_keywords: str) -> dict | None:
    """Content-based lookup first (_tenant_dataset_by_concepts), falling
    back to label-keyword matching only if no column resolved to any of
    these concepts at all -- e.g. a tenant on the LLM-unavailable fallback
    path (schema_discovery._fallback_column_entry always sets concept=None)
    still gets a best-effort match via the label."""
    return _tenant_dataset_by_concepts(tenant_id, *concepts) or _tenant_dataset_by_label(tenant_id, *label_keywords)


def _concept_column_on_dataset(tenant_id: str, dataset_id: int, concept: str, cache: dict) -> str | None:
    """resolve_concept() is tenant-wide, not dataset-scoped -- this checks
    the resolved column actually belongs to `dataset_id` before using it,
    so e.g. a "seats" concept mapped on the customers dataset never gets
    misapplied to a usage-dataset row. Cached per concept per call.

    When multiple columns share the same concept (e.g. several columns all
    mapped to `usage_trend_metric`), we prefer the column whose name
    contains primary business-volume keywords (gmv, revenue, sales, mrr,
    arr, spend) since that is the most meaningful trend signal for churn
    detection. Falls back to the first mapped column if none match.
    """
    cache_key = f"{dataset_id}:{concept}"
    if cache_key not in cache:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT column_name FROM tenant_schema_columns WHERE tenant_id = ? AND dataset_id = ? AND concept = ?",
            (tenant_id, dataset_id, concept)
        )
        rows = [r["column_name"] for r in cur.fetchall()]
        conn.close()
        if not rows:
            cache[cache_key] = None
        elif len(rows) == 1:
            cache[cache_key] = rows[0]
        else:
            # Prefer primary revenue/volume metric column for trend accuracy
            _VOLUME_KEYWORDS = ("gmv", "revenue", "sales", "mrr", "arr", "spend", "transaction", "order_value")
            preferred = next(
                (col for col in rows if any(kw in col.lower() for kw in _VOLUME_KEYWORDS)),
                rows[0]
            )
            cache[cache_key] = preferred
    return cache[cache_key]


def _schema_free_usage_rows(tenant_id: str, customer_id: str) -> list[dict]:
    """
    Normalizes a schema-free tenant's usage-labeled dataset into the shape
    rule_engine.py/prefilter.py/_bandwidth expect (`feature_usage_score`,
    `active_users`, `storage_used_gb`, `storage_limit_gb`, `month`), via
    the concepts schema_discovery.py already resolves for exactly this
    purpose (see its CONCEPTS list). A concept with no mapped column
    defaults to 0 rather than being omitted -- these are numeric fields
    every direct-index caller (compute_usage_trend, storage_pct_used)
    reads without a null check, so 0 is the safe non-crashing default, not
    a claim that the tenant actually has that metric at zero. Rows are
    kept in tenant_records insertion order if no date-like column is
    found for this dataset, which matches upload order for a typical
    monthly usage export.
    """
    dataset = _find_tenant_dataset(tenant_id, _USAGE_CONCEPTS, "usage")
    if not dataset:
        return []

    cache: dict = {}
    schema = get_schema(tenant_id, dataset["id"])
    date_col = next(
        (c["column_name"] for c in schema if c.get("dtype") == "date"), None
    )
    raw_rows = get_dataset_rows(tenant_id, dataset["id"], entity_id=customer_id)

    normalized = []
    for row in raw_rows:
        out = dict(row)
        score_col = _concept_column_on_dataset(tenant_id, dataset["id"], "usage_trend_metric", cache)
        active_col = _concept_column_on_dataset(tenant_id, dataset["id"], "active_users", cache)
        used_col = _concept_column_on_dataset(tenant_id, dataset["id"], "storage_used_gb", cache)
        limit_col = _concept_column_on_dataset(tenant_id, dataset["id"], "storage_limit_gb", cache)
        out["feature_usage_score"] = row.get(score_col) if score_col else 0
        # None (not 0) here means "this tenant has no such concept at all" --
        # distinct from a real, mapped column that happens to read 0.
        # storage_pct_used()/_bandwidth() key off this to hide the
        # dimension entirely for tenants with no storage/seat concept,
        # instead of showing a fabricated 0%/0GB.
        out["active_users"] = row.get(active_col) if active_col else None
        out["storage_used_gb"] = row.get(used_col) if used_col else None
        out["storage_limit_gb"] = row.get(limit_col) if limit_col else None
        out["month"] = row.get(date_col) if date_col else None
        out["extra_attributes"] = {}
        out["is_schema_free_synthetic"] = True
        normalized.append(out)

    if date_col:
        normalized.sort(key=lambda r: str(r.get("month") or ""))
    return normalized


def save_service_usage(tenant_id: str, customer_id: str, month: str, service_name: str,
                        usage_count: float, usage_pct_of_plan: float = None) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO service_usage (tenant_id, customer_id, month, service_name, usage_count, usage_pct_of_plan)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (tenant_id, customer_id, month, service_name, usage_count, usage_pct_of_plan),
    )
    conn.commit()
    conn.close()


def get_service_usage(tenant_id: str, customer_id: str, month: str = None) -> list[dict]:
    """Per-service usage breakdown for a customer -- what they're actually
    using, not just an opaque rollup score. month=None returns every month
    on file."""
    conn = get_connection()
    cur = conn.cursor()
    if month:
        cur.execute(
            "SELECT * FROM service_usage WHERE tenant_id = ? AND customer_id = ? AND month = ? ORDER BY service_name",
            (tenant_id, customer_id, month),
        )
    else:
        cur.execute(
            "SELECT * FROM service_usage WHERE tenant_id = ? AND customer_id = ? ORDER BY month DESC, service_name",
            (tenant_id, customer_id),
        )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Dynamic field registry
# ---------------------------------------------------------------------------
def upsert_dynamic_field(tenant_id: str, dataset_type: str, field_name: str, source_column: str,
                          inferred_type: str, semantic_role: str, description: str,
                          example_values: list, relevance: str, confidence: float) -> None:
    """Records (or updates) an LLM-classified new column so agents can pick
    it up at reasoning time. See app/schema_mapping.py's discovery step."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO dynamic_field_registry
           (tenant_id, dataset_type, field_name, source_column, inferred_type,
            semantic_role, description, example_values, relevance, confidence, discovered_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(tenant_id, dataset_type, field_name) DO UPDATE SET
             source_column = excluded.source_column,
             inferred_type = excluded.inferred_type,
             semantic_role = excluded.semantic_role,
             description = excluded.description,
             example_values = excluded.example_values,
             relevance = excluded.relevance,
             confidence = excluded.confidence""",
        (tenant_id, dataset_type, field_name, source_column, inferred_type, semantic_role,
         description, json.dumps(example_values or []), relevance, confidence),
    )
    conn.commit()
    conn.close()


def get_dynamic_fields(tenant_id: str, dataset_type: str = None, exclude_ignored: bool = True) -> list[dict]:
    """Every dynamic field known for a tenant (optionally scoped to one
    dataset), for injecting into agent prompts and for citation lookups."""
    conn = get_connection()
    cur = conn.cursor()
    query = "SELECT * FROM dynamic_field_registry WHERE tenant_id = ?"
    params = [tenant_id]
    if dataset_type:
        query += " AND dataset_type = ?"
        params.append(dataset_type)
    if exclude_ignored:
        query += " AND relevance != 'ignore'"
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["example_values"] = json.loads(r["example_values"]) if r.get("example_values") else []
    return rows


def get_tickets(tenant_id: str, customer_id: str) -> list[dict]:
    """
    Adapter, same rationale as get_customers()/get_usage() above. Falls
    back to `_schema_free_ticket_rows()` when the legacy `support_tickets`
    table has nothing for this tenant.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM support_tickets WHERE tenant_id = ? AND customer_id = ? ORDER BY created_at DESC",
        (tenant_id, customer_id),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["created_at"] = date.fromisoformat(r["created_at"])

    if rows:
        return rows

    if not list_tenant_datasets(tenant_id):
        return []

    return _schema_free_ticket_rows(tenant_id, customer_id)


def _schema_free_ticket_rows(tenant_id: str, customer_id: str) -> list[dict]:
    """
    Normalizes a schema-free tenant's ticket-labeled dataset into the
    shape prefilter.py/rule_engine.py expect (`category`, `subject`,
    `resolved`, `created_at`).

    `ticket_severity`/`ticket_resolved`/`ticket_created_at` are resolved
    via schema_discovery.py's CONCEPTS the same way usage fields are.
    `category` (billing/security/technical) and `subject` (free text) have
    no equivalent closed-vocabulary concept -- schema_discovery.py
    deliberately keeps CONCEPTS small (design doc §2), so these two are
    resolved with a best-effort heuristic instead: the first
    still-unmapped categorical column stands in for `category`, and the
    first free_text column stands in for `subject`. This is a heuristic,
    not a guaranteed-correct mapping -- unlike the concept-resolved
    fields, a tenant whose ticket dataset happens to have more than one
    categorical/free_text column may get the wrong one. Documented here
    rather than presented as equivalent in reliability to the
    concept-resolved fields above it.

    Fields that resolve to nothing get a safe non-crashing default
    (`category="general"`, `subject=""`, `resolved=False`,
    `created_at=today`) since prefilter.has_relevant_ticket direct-indexes
    `t["category"]`/`t["created_at"]` without a null check.
    """
    dataset = _find_tenant_dataset(tenant_id, _TICKET_CONCEPTS, "ticket", "support")
    if not dataset:
        return []

    cache: dict = {}
    schema = get_schema(tenant_id, dataset["id"])

    severity_col = _concept_column_on_dataset(tenant_id, dataset["id"], "ticket_severity", cache)
    created_col = _concept_column_on_dataset(tenant_id, dataset["id"], "ticket_created_at", cache)
    resolved_col = _concept_column_on_dataset(tenant_id, dataset["id"], "ticket_resolved", cache)

    # No ticket_created_at concept mapped (e.g. the LLM-unavailable fallback
    # never sets concepts) -- fall back to whichever column Stage 1 typed
    # as a date, same signal used for get_usage's date_col.
    if not created_col:
        created_col = next((c["column_name"] for c in schema if c.get("dtype") == "date"), None)

    categorical_cols = [c for c in schema if c.get("dtype") == "categorical"]

    def _distinct_values(column_name: str) -> set:
        raw_rows = get_dataset_rows(tenant_id, dataset["id"])
        return {str(r.get(column_name)).strip().lower() for r in raw_rows if r.get(column_name) is not None}

    def _is_binary_yes_no(column_name: str) -> bool:
        vals = _distinct_values(column_name)
        return vals and vals.issubset({"yes", "no", "true", "false", "resolved", "open", "0", "1"})

    if not resolved_col:
        resolved_col = next(
            (c["column_name"] for c in categorical_cols if _is_binary_yes_no(c["column_name"])),
            None,
        )

    concept_mapped_columns = {c for c in (severity_col, created_col, resolved_col) if c}
    # Prefer a multi-valued categorical column for "category" (e.g.
    # billing/security/technical) over a binary yes/no-looking one, which
    # is far more likely to be a resolved-flag than a ticket category.
    category_candidates = [
        c["column_name"] for c in categorical_cols
        if c["column_name"] not in concept_mapped_columns and not _is_binary_yes_no(c["column_name"])
    ]
    category_col = category_candidates[0] if category_candidates else next(
        (c["column_name"] for c in categorical_cols if c["column_name"] not in concept_mapped_columns),
        None,
    )
    subject_col = next(
        (c["column_name"] for c in schema if c.get("dtype") == "free_text"),
        None,
    )

    raw_rows = get_dataset_rows(tenant_id, dataset["id"], entity_id=customer_id)
    normalized = []
    for row in raw_rows:
        out = dict(row)
        out["category"] = str(row.get(category_col)).lower() if category_col and row.get(category_col) is not None else "general"
        out["subject"] = row.get(subject_col) if subject_col and row.get(subject_col) is not None else ""
        out["severity"] = row.get(severity_col) if severity_col else None
        raw_resolved = row.get(resolved_col) if resolved_col else None
        if raw_resolved is None:
            out["resolved"] = False
        elif isinstance(raw_resolved, str):
            out["resolved"] = raw_resolved.strip().lower() in ("yes", "true", "resolved", "1")
        else:
            out["resolved"] = bool(raw_resolved)

        created_raw = row.get(created_col) if created_col else None
        try:
            out["created_at"] = date.fromisoformat(str(created_raw)[:10]) if created_raw else date.today()
        except ValueError:
            out["created_at"] = date.today()

        out["is_schema_free_synthetic"] = True
        normalized.append(out)

    normalized.sort(key=lambda t: t["created_at"], reverse=True)
    return normalized


def get_product_catalog(tenant_id: str) -> list[dict]:
    """
    Adapter, same rationale as get_customers()/get_usage()/get_tickets()
    above. Falls back to `_schema_free_product_catalog()` when the legacy
    `product_catalog` table has nothing for this tenant. Unlike usage/
    tickets, a catalog dataset has no join_key_column (it's tenant-wide,
    not customer-scoped -- see app.agents.payload's note on this), so
    there's no entity_id to filter by here.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM product_catalog WHERE tenant_id = ?", (tenant_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["extra_attributes"] = json.loads(r["extra_attributes"]) if r.get("extra_attributes") else {}

    if rows:
        return rows

    if not list_tenant_datasets(tenant_id):
        return []

    return _schema_free_product_catalog(tenant_id)


def _schema_free_product_catalog(tenant_id: str) -> list[dict]:
    """
    Normalizes a schema-free tenant's product/catalog-labeled dataset into
    the shape rule_engine.py/web_api.py expect (`product_id`,
    `product_name`, `price_per_seat`, `tier_level`), via
    schema_discovery.py's `product_id`/`product_name`/`price_per_seat`/
    `product_tier_level` concepts.

    `category` (e.g. "core-plan" vs an add-on, used by web_api._next_upsell_product
    to prefer a core-plan upgrade) has no closed-vocabulary concept, same
    caveat as `_schema_free_ticket_rows`'s `category`/`subject` fields --
    resolved with a best-effort heuristic (first unmapped categorical
    column) rather than a guaranteed-correct one, and left out (`None`)
    entirely if no such column exists, which callers already handle via
    `.get("category")`.

    Tier handling: an explicit `product_tier_level` column, when the tenant
    has one, is always preferred (and a row whose explicit tier is missing/
    unparseable is skipped, since overriding a real-but-broken tier with a
    guess would silently corrupt upgrade logic). But many real "any dataset"
    catalogs -- e-commerce/marketplace exports especially (e.g. Amazon
    products have a price but no "plan tier") -- carry no tier column at all.
    Rather than drop every row and block analysis with an empty catalog, we
    then DERIVE an upgrade ordering from price: cheapest distinct price = tier
    1, next = tier 2, and so on, with any row lacking a usable price falling
    to tier 1 (entry). Price rank is a safe, monotonic proxy for "which
    product is a step up" -- and only used when there's no explicit tier to
    corrupt in the first place.
    """
    dataset = _find_tenant_dataset(tenant_id, _CATALOG_CONCEPTS, "product", "catalog")
    if not dataset:
        return []

    cache: dict = {}
    schema = get_schema(tenant_id, dataset["id"])

    id_col = _concept_column_on_dataset(tenant_id, dataset["id"], "product_id", cache)
    name_col = _concept_column_on_dataset(tenant_id, dataset["id"], "product_name", cache)
    price_col = _concept_column_on_dataset(tenant_id, dataset["id"], "price_per_seat", cache)
    tier_col = _concept_column_on_dataset(tenant_id, dataset["id"], "product_tier_level", cache)

    concept_mapped_columns = {c for c in (id_col, name_col, price_col, tier_col) if c}
    category_col = next(
        (c["column_name"] for c in schema
         if c.get("dtype") == "categorical" and c["column_name"] not in concept_mapped_columns),
        None,
    )

    raw_rows = get_dataset_rows(tenant_id, dataset["id"])

    def _price_of(row: dict) -> float | None:
        raw = row.get(price_col) if price_col else None
        if raw in (None, "", "None", "none", "nan"):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    # No explicit tier column -> derive a price-rank tier map (see docstring).
    price_rank = None
    if not tier_col:
        distinct_prices = sorted({p for row in raw_rows if (p := _price_of(row)) is not None})
        price_rank = {p: i + 1 for i, p in enumerate(distinct_prices)}

    normalized = []
    for row in raw_rows:
        name = row.get(name_col) if name_col else None
        if not name:
            continue
        price = _price_of(row)
        if tier_col:
            tier_raw = row.get(tier_col)
            if tier_raw is None:
                continue
            try:
                tier_level = int(tier_raw)
            except (TypeError, ValueError):
                continue
        else:
            # Derived: price rank, or entry tier (1) when this row has no price.
            tier_level = price_rank.get(price, 1) if price is not None else 1

        out = dict(row)
        out["product_id"] = row.get(id_col) if id_col else name
        out["product_name"] = name
        out["tier_level"] = tier_level
        out["price_per_seat"] = price if price is not None else 0.0
        out["category"] = row.get(category_col) if category_col else None
        out["extra_attributes"] = {}
        out["is_schema_free_synthetic"] = True
        normalized.append(out)

    return normalized


def _schema_free_dataset_row_count(tenant_id: str, concepts: tuple[str, ...], *label_keywords: str) -> int:
    """Row count for a schema-free tenant's usage/ticket/catalog dataset,
    found the same way get_usage()/get_tickets()/get_product_catalog()
    themselves find it (_find_tenant_dataset: concept-content match first,
    label-keyword fallback second). Returns 0 if the tenant has no such
    dataset -- used by tenant_dataset_counts() so the "was this ever
    uploaded" check covers schema-free tenants too, not just the legacy
    fixed tables, and agrees with what analysis actually reads."""
    dataset = _find_tenant_dataset(tenant_id, concepts, *label_keywords)
    if not dataset:
        return 0
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS n FROM tenant_records WHERE tenant_id = ? AND dataset_id = ?",
        (tenant_id, dataset["id"]),
    )
    n = cur.fetchone()["n"]
    conn.close()
    return n


def tenant_dataset_counts(tenant_id: str) -> dict:
    """Row counts per core "dataset kind" for this tenant -- used to tell
    "this dataset was never uploaded" apart from "this customer legitimately
    has zero tickets/usage rows". Checked once per tenant (not per
    customer), since these are tenant-wide uploads.

    Adapter (schema_free_pipeline_design.md gap fix, same rationale as
    get_customers()/get_usage()/get_tickets() above): a schema-free tenant's
    usage/ticket/catalog data lives in tenant_records, never in the legacy
    usage_metrics/support_tickets/product_catalog tables, so checking only
    those legacy tables made every schema-free tenant's dashboard show
    "no usage metrics uploaded" / "no support ticket data uploaded" gap
    warnings even when that data was successfully ingested and IS being
    used by get_usage()/get_tickets() at analysis time. Falls back to the
    schema-free dataset-label match (_tenant_dataset_by_label) whenever the
    legacy table has nothing for this tenant, mirroring exactly how
    get_usage()/get_tickets() themselves decide which source to read from.

    product_catalog is still counted as source='upload' only for the legacy
    path -- rows written by the onboarding auto-seed fallback
    (app/onboarding.py, source='demo_seed') are real rows the pipeline can
    use, but they are NOT this tenant's own catalog, so they must not
    suppress the "no product catalog uploaded" gap warning. A schema-free
    tenant's own uploaded catalog dataset counts as a real upload, same as
    the legacy path's source='upload' rows.
    """
    conn = get_connection()
    cur = conn.cursor()
    counts = {}
    for table in ("usage_metrics", "support_tickets"):
        cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE tenant_id = ?", (tenant_id,))
        counts[table] = cur.fetchone()["n"]
    cur.execute(
        "SELECT COUNT(*) AS n FROM product_catalog WHERE tenant_id = ? AND source = 'upload'",
        (tenant_id,),
    )
    counts["product_catalog"] = cur.fetchone()["n"]
    cur.execute(
        "SELECT COUNT(*) AS n FROM product_catalog WHERE tenant_id = ? AND source = 'demo_seed'",
        (tenant_id,),
    )
    counts["product_catalog_demo_seed"] = cur.fetchone()["n"]
    conn.close()

    if counts["usage_metrics"] == 0:
        counts["usage_metrics"] = _schema_free_dataset_row_count(tenant_id, _USAGE_CONCEPTS, "usage")
    if counts["support_tickets"] == 0:
        counts["support_tickets"] = _schema_free_dataset_row_count(tenant_id, _TICKET_CONCEPTS, "ticket", "support")
    if counts["product_catalog"] == 0:
        counts["product_catalog"] = _schema_free_dataset_row_count(tenant_id, _CATALOG_CONCEPTS, "product", "catalog")

    return counts


def save_product_embedding(tenant_id: str, product_id: str, embedding, embedded_text: str, model_name: str) -> None:
    """embedding is a numpy array; stored as raw float32 bytes."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO product_embeddings (tenant_id, product_id, embedding, embedded_text, model_name, embedded_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(tenant_id, product_id) DO UPDATE SET
             embedding = excluded.embedding,
             embedded_text = excluded.embedded_text,
             model_name = excluded.model_name,
             embedded_at = excluded.embedded_at""",
        (tenant_id, product_id, embedding.astype("float32").tobytes(), embedded_text, model_name),
    )
    conn.commit()
    conn.close()


def get_all_product_embeddings(tenant_id: str) -> dict:
    """Returns {product_id: np.ndarray(float32)} for every embedded product
    belonging to this tenant."""
    import numpy as np

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT product_id, embedding FROM product_embeddings WHERE tenant_id = ?", (tenant_id,))
    rows = cur.fetchall()
    conn.close()
    return {r["product_id"]: np.frombuffer(r["embedding"], dtype="float32") for r in rows}


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------
def log_recommendation(tenant_id: str, rec: dict) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO recommendations_log
           (tenant_id, customer_id, customer_name, segment, churn_risk, churn_reason,
            recommended_product, recommendation_type, rationale, revenue_score, confidence,
            estimated_deal_value, renewal_date, generated_at, agent_trace, outcome,
            no_recommendation_reason_code, retention_action)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
        (
            tenant_id, rec["customer_id"], rec["customer_name"], rec["segment"], rec["churn_risk"],
            rec["churn_reason"], rec.get("recommended_product"), rec.get("recommendation_type"),
            rec["rationale"], rec["revenue_score"], rec.get("confidence"),
            rec.get("estimated_deal_value", 0),
            rec["renewal_date"], rec["generated_at"], json.dumps(rec.get("agent_trace")),
            rec.get("no_recommendation_reason_code"),
            json.dumps(rec.get("retention_action")) if rec.get("retention_action") else None,
        ),
    )
    conn.commit()
    rec_id = cur.lastrowid
    conn.close()
    return rec_id


def get_latest_recommendations(tenant_id: str) -> list[dict]:
    """Returns the most recent recommendation per customer for this tenant,
    ranked by score."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.* FROM recommendations_log r
        INNER JOIN (
            SELECT customer_id, MAX(generated_at) AS max_gen
            FROM recommendations_log
            WHERE tenant_id = ?
            GROUP BY customer_id
        ) latest
        ON r.customer_id = latest.customer_id AND r.generated_at = latest.max_gen
        WHERE r.tenant_id = ?
        ORDER BY r.confidence IS NULL, r.confidence DESC, r.revenue_score DESC
        """,
        (tenant_id, tenant_id),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_recommendation_by_id(tenant_id: str, rec_id: int) -> dict | None:
    """Scoped by tenant_id as well as rec_id -- a valid rec_id belonging to
    another tenant must not be readable/updatable just by guessing the int."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM recommendations_log WHERE id = ? AND tenant_id = ?", (rec_id, tenant_id))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_outcome(tenant_id: str, rec_id: int, outcome: str) -> bool:
    """Returns False (and updates nothing) if rec_id doesn't belong to tenant_id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE recommendations_log SET outcome = ? WHERE id = ? AND tenant_id = ?",
        (outcome, rec_id, tenant_id),
    )
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_recommendations_with_outcomes(tenant_id: str) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM recommendations_log WHERE tenant_id = ? AND outcome IS NOT NULL",
        (tenant_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Tenant profile / config / column mappings
# ---------------------------------------------------------------------------
def save_tenant_profile(profile: dict) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT OR REPLACE INTO tenant_profiles
           (tenant_id, usage_baseline_p50, usage_baseline_p90, usage_growth_p75,
            storage_threshold_pct, avg_deal_size, renewal_window_days, total_customers,
            sample_size, min_score_threshold, calibrated_at, calibration_source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            profile["tenant_id"], profile.get("usage_baseline_p50"),
            profile.get("usage_baseline_p90"), profile.get("usage_growth_p75"),
            profile.get("storage_threshold_pct"), profile.get("avg_deal_size"),
            profile.get("renewal_window_days"), profile.get("total_customers"),
            profile.get("sample_size"),
            profile.get("min_score_threshold"), profile.get("calibrated_at"),
            profile.get("calibration_source"),
        ),
    )
    conn.commit()
    conn.close()


def get_tenant_profile(tenant_id: str) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tenant_profiles WHERE tenant_id = ?", (tenant_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_tenant_config(tenant_id: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tenant_config WHERE tenant_id = ?", (tenant_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        result = dict(row)
        # Normalize old tenant rows created before the IndiaAI-only migration.
        result["llm_provider"] = "indiaai"
        return result
    # Default: AI-written explanations ON (via IndiaAI) out of the box, with an
    # automatic rule-based fallback whenever the configured LLM provider is
    # unavailable. No vector search until the catalog is embedded.
    return {"tenant_id": tenant_id, "use_llm": True, "llm_provider": "indiaai",
            "use_vector_search": False, "onboarded_at": None, "column_mapping_confirmed": False,
            "revenue_model": "recurring"}


def set_tenant_config(tenant_id: str, use_llm: bool = True, llm_provider: str = "indiaai",
                       use_vector_search: bool = False, revenue_model: str | None = None) -> None:
    """
    revenue_model: "recurring" (SaaS-style -- price_per_seat is a monthly
    rate) or "one_time" (retail/goods -- price_per_seat is a per-unit
    price). Controls whether the catalog's potential-revenue figure is
    labeled "/mo" on the frontend. None leaves any existing stored value
    untouched (via COALESCE) instead of silently resetting it back to the
    'recurring' column default on every unrelated config update.
    """
    llm_provider = "indiaai"  # Single provider, including when old clients submit another value.
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tenant_config (tenant_id, use_llm, llm_provider, use_vector_search, onboarded_at, column_mapping_confirmed, revenue_model)
           VALUES (?, ?, ?, ?, datetime('now'), 0, COALESCE(?, 'recurring'))
           ON CONFLICT(tenant_id) DO UPDATE SET
             use_llm = excluded.use_llm,
             llm_provider = excluded.llm_provider,
             use_vector_search = excluded.use_vector_search,
             revenue_model = COALESCE(?, tenant_config.revenue_model)""",
        (tenant_id, use_llm, llm_provider, use_vector_search, revenue_model, revenue_model),
    )
    conn.commit()
    conn.close()


def mark_column_mapping_confirmed(tenant_id: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tenant_config (tenant_id, column_mapping_confirmed, onboarded_at)
           VALUES (?, 1, datetime('now'))
           ON CONFLICT(tenant_id) DO UPDATE SET column_mapping_confirmed = 1""",
        (tenant_id,),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Upserts (ingestion) -- all scoped by tenant_id in both the key and the
# ON CONFLICT clause, so re-ingesting tenant B can never touch tenant A's
# row even if the source IDs are identical.
# ---------------------------------------------------------------------------
def upsert_customers(tenant_id: str, rows: list[dict]) -> int:
    """
    Insert or update customer rows for one tenant. `rows` are already
    column-mapped to internal field names by data_ingestion.py before this
    is called -- this function assumes correct keys and does no renaming.
    Any columns the tenant had that don't map to a known field arrive under
    `extra_attributes` (a dict) and are stored as JSON -- see
    app/schema_mapping.py's discover_unmapped_columns().
    """
    conn = get_connection()
    cur = conn.cursor()
    for r in rows:
        cur.execute(
            """INSERT INTO customers
               (tenant_id, customer_id, customer_name, industry, plan_tier, seats,
                contract_start_date, renewal_date, account_manager, extra_attributes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id, customer_id) DO UPDATE SET
                 customer_name = excluded.customer_name,
                 industry = excluded.industry,
                 plan_tier = excluded.plan_tier,
                 seats = excluded.seats,
                 contract_start_date = excluded.contract_start_date,
                 renewal_date = excluded.renewal_date,
                 account_manager = excluded.account_manager,
                 extra_attributes = excluded.extra_attributes""",
            (
                tenant_id, r["customer_id"], r["customer_name"], r.get("industry"),
                r.get("plan_tier"), r.get("seats"), r.get("contract_start_date"),
                r["renewal_date"], r.get("account_manager"),
                json.dumps(r["extra_attributes"]) if r.get("extra_attributes") else None,
            ),
        )
    conn.commit()
    conn.close()
    return len(rows)


def upsert_usage_metrics(tenant_id: str, rows: list[dict]) -> int:
    """
    Usage rows have no natural unique key in the schema (id is autoincrement),
    so a re-upload for the same tenant/customer_id/month would otherwise
    create a duplicate row rather than update the existing one. Delete-then-
    insert per (tenant_id, customer_id, month) keeps re-uploads idempotent
    without touching any other tenant's rows.
    """
    conn = get_connection()
    cur = conn.cursor()
    for r in rows:
        cur.execute(
            "DELETE FROM usage_metrics WHERE tenant_id = ? AND customer_id = ? AND month = ?",
            (tenant_id, r["customer_id"], r["month"]),
        )
        cur.execute(
            """INSERT INTO usage_metrics
               (tenant_id, customer_id, month, active_users, storage_used_gb, storage_limit_gb,
                feature_usage_score, extra_attributes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tenant_id, r["customer_id"], r["month"], r.get("active_users"),
                r.get("storage_used_gb"), r.get("storage_limit_gb"), r.get("feature_usage_score"),
                json.dumps(r["extra_attributes"]) if r.get("extra_attributes") else None,
            ),
        )
    conn.commit()
    conn.close()
    return len(rows)


def upsert_support_tickets(tenant_id: str, rows: list[dict]) -> int:
    conn = get_connection()
    cur = conn.cursor()
    for r in rows:
        cur.execute(
            """INSERT INTO support_tickets
               (tenant_id, ticket_id, customer_id, created_at, category, subject, resolved, extra_attributes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id, ticket_id) DO UPDATE SET
                 customer_id = excluded.customer_id,
                 created_at = excluded.created_at,
                 category = excluded.category,
                 subject = excluded.subject,
                 resolved = excluded.resolved,
                 extra_attributes = excluded.extra_attributes""",
            (
                tenant_id, r["ticket_id"], r["customer_id"], r["created_at"],
                r.get("category"), r.get("subject"), r.get("resolved"),
                json.dumps(r["extra_attributes"]) if r.get("extra_attributes") else None,
            ),
        )
    conn.commit()
    conn.close()
    return len(rows)


def upsert_product_catalog(tenant_id: str, rows: list[dict]) -> int:
    """Writes rows from an actual tenant-uploaded catalog file (see
    app/data_ingestion.py) -- always tagged source='upload', which on
    conflict overwrites any prior 'demo_seed' row so a real upload
    correctly supersedes the onboarding auto-seed fallback."""
    conn = get_connection()
    cur = conn.cursor()
    for r in rows:
        cur.execute(
            """INSERT INTO product_catalog
               (tenant_id, product_id, product_name, tier_level, price_per_seat, complements,
                category, description, extra_attributes, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'upload')
               ON CONFLICT(tenant_id, product_id) DO UPDATE SET
                 product_name = excluded.product_name,
                 tier_level = excluded.tier_level,
                 price_per_seat = excluded.price_per_seat,
                 complements = excluded.complements,
                 category = excluded.category,
                 description = excluded.description,
                 extra_attributes = excluded.extra_attributes,
                 source = 'upload'""",
            (
                tenant_id, r["product_id"], r["product_name"], r.get("tier_level"),
                r.get("price_per_seat"), r.get("complements"), r.get("category"), r.get("description"),
                json.dumps(r["extra_attributes"]) if r.get("extra_attributes") else None,
            ),
        )
    conn.commit()
    conn.close()
    return len(rows)


def get_customer_full_profile(tenant_id: str, customer_id: str) -> dict:
    customers = get_customers(tenant_id, [customer_id])
    if not customers:
        return {}
    customer = customers[0]
    customer["usage"] = get_usage(tenant_id, customer_id)
    customer["tickets"] = get_tickets(tenant_id, customer_id)
    customer["service_usage"] = get_service_usage(tenant_id, customer_id)
    return customer


# ---------------------------------------------------------------------------
# Schema-free ingestion model (see schema_free_pipeline_design.md).
# Generic accessors replacing dataset-specific ones (get_usage/get_tickets/
# etc.) for tenants ingested through the new Schema Discovery pipeline.
# ---------------------------------------------------------------------------

def upsert_tenant_dataset(tenant_id: str, dataset_label: str, original_filename: str,
                           row_count: int, join_key_column: str | None,
                           schema_version: str) -> int:
    """Insert or update the tenant_datasets row for one uploaded file. Returns dataset_id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM tenant_datasets WHERE tenant_id = ? AND original_filename = ?",
        (tenant_id, original_filename),
    )
    existing = cur.fetchone()
    now = datetime.utcnow().isoformat()
    if existing:
        dataset_id = existing["id"]
        cur.execute(
            """UPDATE tenant_datasets SET dataset_label = ?, row_count = ?,
               join_key_column = ?, schema_version = ?, discovered_at = ? WHERE id = ?""",
            (dataset_label, row_count, join_key_column, schema_version, now, dataset_id),
        )
    else:
        cur.execute(
            """INSERT INTO tenant_datasets
               (tenant_id, dataset_label, original_filename, row_count, join_key_column,
                schema_version, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tenant_id, dataset_label, original_filename, row_count, join_key_column,
             schema_version, now),
        )
        dataset_id = cur.lastrowid
    conn.commit()
    conn.close()
    return dataset_id


def get_tenant_dataset(tenant_id: str, original_filename: str) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM tenant_datasets WHERE tenant_id = ? AND original_filename = ?",
        (tenant_id, original_filename),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def list_tenant_datasets(tenant_id: str) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tenant_datasets WHERE tenant_id = ?", (tenant_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def replace_tenant_schema_columns(tenant_id: str, dataset_id: int, columns: list[dict]) -> None:
    """
    Replaces the full column catalog for one dataset. Called once per
    Stage-1 discovery run (initial upload or re-upload) -- always wipes and
    rewrites rather than diffing, since a re-upload can rename/drop/add
    columns freely and there's no stable identity for a column across runs
    other than its name.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tenant_schema_columns WHERE tenant_id = ? AND dataset_id = ?",
                (tenant_id, dataset_id))
    for col in columns:
        cur.execute(
            """INSERT INTO tenant_schema_columns
               (tenant_id, dataset_id, column_name, inferred_label, description, dtype,
                semantic_role, relevance, concept, stats_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tenant_id, dataset_id, col["column"], col.get("inferred_label"),
             col.get("description"), col.get("dtype"), col.get("semantic_role"),
             col.get("relevance"), col.get("concept"),
             json.dumps(col.get("stats")) if col.get("stats") else None),
        )
    conn.commit()
    conn.close()


def get_schema(tenant_id: str, dataset_id: int) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tenant_schema_columns WHERE tenant_id = ? AND dataset_id = ?",
                (tenant_id, dataset_id))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_tenant_schema_catalog(tenant_id: str) -> list[dict]:
    """All columns across all of a tenant's datasets, each annotated with its
    dataset_label -- the combined catalog the Prompt Architect Agent (Stage 2)
    consumes."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT sc.*, d.dataset_label, d.original_filename
           FROM tenant_schema_columns sc
           JOIN tenant_datasets d ON d.id = sc.dataset_id
           WHERE sc.tenant_id = ?""",
        (tenant_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _json_default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


def replace_tenant_records(tenant_id: str, dataset_id: int, records: list[dict]) -> int:
    """records: list of {"entity_id": str|None, "row": dict}. Wipes and
    rewrites this dataset's rows, same reasoning as replace_tenant_schema_columns."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tenant_records WHERE tenant_id = ? AND dataset_id = ?",
                (tenant_id, dataset_id))
    for rec in records:
        cur.execute(
            "INSERT INTO tenant_records (tenant_id, dataset_id, entity_id, row_json) VALUES (?, ?, ?, ?)",
            (tenant_id, dataset_id, rec.get("entity_id"), json.dumps(rec["row"], default=_json_default)),
        )
    conn.commit()
    conn.close()
    return len(records)


def get_dataset_rows(tenant_id: str, dataset_id: int, entity_id: str | None = None) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    if entity_id is not None:
        cur.execute(
            "SELECT entity_id, row_json FROM tenant_records WHERE tenant_id = ? AND dataset_id = ? AND entity_id = ?",
            (tenant_id, dataset_id, entity_id),
        )
    else:
        cur.execute(
            "SELECT entity_id, row_json FROM tenant_records WHERE tenant_id = ? AND dataset_id = ?",
            (tenant_id, dataset_id),
        )
    rows = []
    for r in cur.fetchall():
        row = json.loads(r["row_json"])
        rows.append(row)
    conn.close()
    return rows


def get_unmapped_customer_fields(tenant_id: str, customer_id: str, limit: int = 3) -> list[dict]:
    """Every unmapped (concept IS NULL), non-noise column across this
    tenant's datasets that has a non-null value for this specific
    customer -- the schema-free-native way to surface genuinely
    tenant-specific "surprise" columns (NPS, CSAT, loyalty signups, safety
    incidents, ...) without a keyword whitelist or a closed concept for
    each one.

    Fix (see app/insights.py's _surprise_field_insights): the previous
    mechanism for this (app.dynamic_context.build_dynamic_field_context)
    reads customer["extra_attributes"] and the legacy dynamic_field_registry
    table -- both are artifacts of the old fixed-schema onboarding flow.
    A schema-free tenant's synthesized customer dict always has
    extra_attributes={} (see _build_synthetic_customer above) and Stage 1
    discovery never writes dynamic_field_registry at all, so that whole
    path was silently dead for every schema-free tenant regardless of what
    "surprise" columns their data actually had. This reads the real
    schema-free tables instead.

    Ordered by relevance (high before medium), capped at `limit` so a wide,
    noisy dataset doesn't spam every customer page with low-value fields.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT * FROM tenant_schema_columns
           WHERE tenant_id = ? AND concept IS NULL AND relevance IN ('high', 'medium')""",
        (tenant_id,),
    )
    cols = [dict(r) for r in cur.fetchall() if (r["semantic_role"] or "") != "noise"]
    conn.close()

    order = {"high": 0, "medium": 1}
    cols.sort(key=lambda c: order.get(c.get("relevance"), 2))

    out = []
    seen_names = set()
    for col in cols:
        if col["column_name"] in seen_names:
            continue
        rows = get_dataset_rows(tenant_id, col["dataset_id"], entity_id=customer_id)
        if not rows:
            continue
        value = rows[0].get(col["column_name"])
        if value is None:
            continue
        seen_names.add(col["column_name"])
        out.append({
            "field_name": col["column_name"],
            "label": col.get("inferred_label") or col["column_name"],
            "description": col.get("description") or "",
            "value": value,
        })
        if len(out) >= limit:
            break
    return out


def resolve_concept(tenant_id: str, concept_name: str) -> dict | None:
    """
    Returns {"dataset_id": ..., "column_name": ...} for the column mapped to
    `concept_name` for this tenant, or None if no column maps to it (in
    which case the caller -- rule_engine.py fallback, web_api.py's
    _churn/_bandwidth/_mrr -- must report "insufficient data" rather than
    default to a fake neutral value).

    If multiple columns map to the same concept (shouldn't normally happen,
    but data is messy), the first match wins and a warning is logged by the
    caller if it cares.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT dataset_id, column_name FROM tenant_schema_columns WHERE tenant_id = ? AND concept = ? LIMIT 1",
        (tenant_id, concept_name),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def save_tenant_prompt_spec(tenant_id: str, prompt_spec: str, possible_insight_categories: list,
                             excluded_insight_categories: list, schema_fingerprint: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tenant_prompt_specs
           (tenant_id, prompt_spec, possible_insight_categories, excluded_insight_categories,
            schema_fingerprint, compiled_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(tenant_id) DO UPDATE SET
             prompt_spec=excluded.prompt_spec,
             possible_insight_categories=excluded.possible_insight_categories,
             excluded_insight_categories=excluded.excluded_insight_categories,
             schema_fingerprint=excluded.schema_fingerprint,
             compiled_at=excluded.compiled_at""",
        (tenant_id, prompt_spec, json.dumps(possible_insight_categories),
         json.dumps(excluded_insight_categories), schema_fingerprint, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_tenant_prompt_spec(tenant_id: str) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tenant_prompt_specs WHERE tenant_id = ?", (tenant_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["possible_insight_categories"] = json.loads(d["possible_insight_categories"] or "[]")
    d["excluded_insight_categories"] = json.loads(d["excluded_insight_categories"] or "[]")
    return d


# ---------------------------------------------------------------------------
# Stage 3: bounded self-correction loop -- unresolved data gaps.
# ---------------------------------------------------------------------------

def record_schema_gap(tenant_id: str, concept: str | None, flag_type: str, detail: str,
                       sample_customers: list[str]) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tenant_schema_gaps
           (tenant_id, concept, flag_type, detail, sample_customers, resolved, recorded_at)
           VALUES (?, ?, ?, ?, ?, 0, ?)""",
        (tenant_id, concept, flag_type, detail, json.dumps(sample_customers), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_tenant_schema_gaps(tenant_id: str, unresolved_only: bool = True) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    if unresolved_only:
        cur.execute("SELECT * FROM tenant_schema_gaps WHERE tenant_id = ? AND resolved = 0", (tenant_id,))
    else:
        cur.execute("SELECT * FROM tenant_schema_gaps WHERE tenant_id = ?", (tenant_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["sample_customers"] = json.loads(r["sample_customers"] or "[]")
    return rows


def clear_tenant_schema_gaps(tenant_id: str) -> None:
    """Called at the start of each Stage-3 run for a tenant -- gaps are
    recomputed fresh each time rather than accumulating stale entries from
    a previous ingestion run."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tenant_schema_gaps WHERE tenant_id = ?", (tenant_id,))
    conn.commit()
    conn.close()


def set_column_concept(tenant_id: str, dataset_id: int, column_name: str, concept: str) -> None:
    """Used by schema_discovery.reexamine_concept() (Stage 3) to map a
    previously-unmapped column to a concept after re-examination confirms it."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE tenant_schema_columns SET concept = ? WHERE tenant_id = ? AND dataset_id = ? AND column_name = ?",
        (concept, tenant_id, dataset_id, column_name),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Feature weights
# ---------------------------------------------------------------------------
def get_feature_weights(tenant_id: str) -> dict:
    """Returns feature weight dict for the tenant. Empty dict = defaults."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tenant_feature_weights (
                tenant_id TEXT NOT NULL, feature_name TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0, updated_at TEXT,
                PRIMARY KEY (tenant_id, feature_name)
            )
        """)
        rows = conn.execute(
            "SELECT feature_name, weight FROM tenant_feature_weights WHERE tenant_id = ?",
            (tenant_id,)
        ).fetchall()
        return {r["feature_name"]: r["weight"] for r in rows}
    finally:
        conn.close()


def set_feature_weights(tenant_id: str, weights: dict) -> dict:
    """Upserts feature weights for a tenant."""
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tenant_feature_weights (
                tenant_id TEXT NOT NULL, feature_name TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0, updated_at TEXT,
                PRIMARY KEY (tenant_id, feature_name)
            )
        """)
        for name, weight in weights.items():
            conn.execute("""
                INSERT INTO tenant_feature_weights (tenant_id, feature_name, weight, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (tenant_id, feature_name)
                DO UPDATE SET weight = excluded.weight, updated_at = excluded.updated_at
            """, (tenant_id, str(name), float(weight), now))
        conn.commit()
        return get_feature_weights(tenant_id)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Catalog CRUD
# ---------------------------------------------------------------------------
def add_catalog_product(tenant_id: str, product_name: str, category: str,
                        tier_level: int, price_per_seat: float, description: str = None) -> dict:
    """Adds a custom product to the tenant catalog."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO product_catalog (tenant_id, product_name, category, tier_level, price_per_seat, description, source) VALUES (?, ?, ?, ?, ?, ?, 'custom')",
            (tenant_id, product_name, category, tier_level, price_per_seat, description)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM product_catalog WHERE rowid = ?", (cur.lastrowid,)).fetchone()
        return dict(row) if row else {"product_name": product_name}
    finally:
        conn.close()


def remove_catalog_product(tenant_id: str, product_id: int) -> bool:
    """Deletes a product from the tenant catalog."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM product_catalog WHERE product_id = ? AND tenant_id = ?",
            (product_id, tenant_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_catalog_product(tenant_id: str, product_id: int, updates: dict) -> dict | None:
    """Updates fields on an existing catalog product."""
    allowed = {"product_name", "category", "tier_level", "price_per_seat", "description"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return None
    conn = get_connection()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE product_catalog SET {set_clause} WHERE product_id = ? AND tenant_id = ?",
            list(fields.values()) + [product_id, tenant_id]
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM product_catalog WHERE product_id = ? AND tenant_id = ?",
            (product_id, tenant_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Login attempt tracking
# ---------------------------------------------------------------------------
def _ensure_login_attempts_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL, success INTEGER NOT NULL DEFAULT 0,
            attempted_at TEXT NOT NULL
        )
    """)


def record_login_attempt(email: str, success: bool) -> None:
    from datetime import datetime
    conn = get_connection()
    try:
        _ensure_login_attempts_table(conn)
        conn.execute(
            "INSERT INTO login_attempts (email, success, attempted_at) VALUES (?, ?, ?)",
            (email, 1 if success else 0, datetime.utcnow().isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def count_recent_failed_logins(email: str, window_minutes: int = 10) -> int:
    from datetime import datetime, timedelta
    conn = get_connection()
    try:
        _ensure_login_attempts_table(conn)
        cutoff = (datetime.utcnow() - timedelta(minutes=window_minutes)).isoformat()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM login_attempts WHERE email = ? AND success = 0 AND attempted_at > ?",
            (email, cutoff)
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()