-- Upsell Recommendation Agent — database schema (v2: multi-tenant)
--
-- Every core data table is now scoped by tenant_id as part of its identity
-- (composite primary key), not just an extra column. This means:
--   - Two tenants can both have a customer/ticket/product with the same
--     source ID without colliding or overwriting each other.
--   - No query against these tables can accidentally return another
--     tenant's rows -- tenant_id is required in every WHERE clause AND
--     every uniqueness/conflict constraint (see app/db.py).
--
-- v1 (single shared table, no tenant_id) is NOT migrated automatically --
-- see app/db.py's init_db() for why (source IDs across tenants may already
-- collide/have overwritten each other under the old schema, so there is
-- nothing safe to migrate).

CREATE TABLE IF NOT EXISTS customers (
    tenant_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    industry TEXT,
    plan_tier TEXT,
    seats INTEGER,
    contract_start_date DATE,
    renewal_date DATE,
    account_manager TEXT,
    archetype TEXT,  -- internal only: which synthetic pattern generated this row
    extra_attributes JSON,  -- tenant-specific columns with no fixed field yet; see dynamic_field_registry
    PRIMARY KEY (tenant_id, customer_id)
);

CREATE TABLE IF NOT EXISTS usage_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    month DATE,
    active_users INTEGER,
    storage_used_gb REAL,
    storage_limit_gb REAL,
    feature_usage_score REAL,  -- rollup, derived from service_usage rows for this customer/month (see app/usage_rollup.py)
    extra_attributes JSON,
    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers(tenant_id, customer_id)
);

-- Per-service usage breakdown -- replaces "feature_usage_score" as an opaque
-- input. feature_usage_score above is now a *derived* weighted rollup of
-- these rows, so agents/rationale text can say what a customer is actually
-- using instead of citing one unexplained number.
CREATE TABLE IF NOT EXISTS service_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    month DATE,
    service_name TEXT,       -- e.g. 'analytics_dashboard', 'api_access', 'sso', 'reporting'
    usage_count REAL,        -- raw count/hours/calls -- unit is per-service, kept in service_name convention
    usage_pct_of_plan REAL,  -- normalized against plan entitlement, NULL if not applicable
    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers(tenant_id, customer_id)
);

CREATE TABLE IF NOT EXISTS support_tickets (
    tenant_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    created_at DATE,
    category TEXT,
    subject TEXT,
    resolved BOOLEAN,
    extra_attributes JSON,
    PRIMARY KEY (tenant_id, ticket_id),
    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers(tenant_id, customer_id)
);

CREATE TABLE IF NOT EXISTS product_catalog (
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    product_name TEXT,
    tier_level INTEGER,
    price_per_seat REAL,
    complements TEXT,
    category TEXT,        -- optional, improves vector-search text (e.g. 'security', 'analytics')
    description TEXT,     -- optional, improves vector-search text
    extra_attributes JSON,
    source TEXT DEFAULT 'upload',   -- 'upload' (tenant's own ingested file) or 'demo_seed' (auto-seeded fallback, see app/onboarding.py)
    PRIMARY KEY (tenant_id, product_id)
);

-- Local embeddings for semantic product matching (ticket -> product, product ->
-- complements). Kept in its own table so re-embedding never touches core
-- catalog data, and so a tenant who never enables vector search never pays
-- for it -- this table just stays empty for them.
CREATE TABLE IF NOT EXISTS product_embeddings (
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    embedding BLOB NOT NULL,       -- float32 numpy array, serialized via .tobytes()
    embedded_text TEXT NOT NULL,   -- exact text that was embedded, for debugging/re-embedding
    model_name TEXT NOT NULL,
    embedded_at TIMESTAMP,
    PRIMARY KEY (tenant_id, product_id),
    FOREIGN KEY (tenant_id, product_id) REFERENCES product_catalog(tenant_id, product_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    tenant_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    customer_id TEXT,
    product_id TEXT,
    purchase_date DATE,
    amount REAL,
    PRIMARY KEY (tenant_id, transaction_id)
);

CREATE TABLE IF NOT EXISTS tenant_config (
    tenant_id TEXT PRIMARY KEY,
    use_llm BOOLEAN DEFAULT 0,          -- 0 = rule-based only (default, works with no API key)
                                         -- 1 = LLM-enhanced rationale/reasoning
    llm_provider TEXT DEFAULT NULL,     -- 'indiaai' only
    use_vector_search BOOLEAN DEFAULT 0, -- 0 = keyword matching (default, no extra deps)
                                          -- 1 = local sentence-transformer embeddings
    onboarded_at TIMESTAMP,
    column_mapping_confirmed BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS column_mappings (
    tenant_id TEXT,
    dataset_type TEXT,                  -- 'customers' | 'usage_metrics' | 'support_tickets' | 'product_catalog'
    internal_field TEXT,                -- e.g. 'renewal_date', 'seats', 'usage_score'
    source_column TEXT,                 -- the tenant's actual column name, e.g. 'Contract_End_Date'
    confirmed_by_user BOOLEAN DEFAULT 0, -- 0 = auto-suggested only, 1 = user confirmed
    PRIMARY KEY (tenant_id, dataset_type, internal_field)
);

CREATE TABLE IF NOT EXISTS tenant_profiles (
    tenant_id TEXT PRIMARY KEY,
    usage_baseline_p50 REAL,        -- median feature_usage_score across this tenant's customers
    usage_baseline_p90 REAL,        -- 90th percentile -- used to define "high usage" relative to THIS tenant
    usage_growth_p75 REAL,          -- 75th percentile of usage trend % -- defines "notable growth" for this tenant
    storage_threshold_pct REAL,     -- calibrated storage-utilization trigger (defaults to 80 if not enough data)
    avg_deal_size REAL,             -- average estimated_deal_value across this tenant's product catalog x seats
    renewal_window_days INTEGER,    -- calibrated renewal lookback window (defaults to 90)
    total_customers INTEGER,        -- total customers on this tenant's roster (may be > sample_size, which only counts customers with usage history)
    sample_size INTEGER,            -- how many customers had usage history and were actually used to compute this calibration
    min_score_threshold REAL,       -- recalibrated from outcome feedback once enough data exists
    calibrated_at TIMESTAMP,
    calibration_source TEXT         -- 'initial_onboarding' or 'feedback_recalibration'
);

CREATE TABLE IF NOT EXISTS recommendations_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    customer_id TEXT,
    customer_name TEXT,
    segment TEXT,
    churn_risk TEXT,
    churn_reason TEXT,
    recommended_product TEXT,
    recommendation_type TEXT,
    rationale TEXT,
    revenue_score REAL,
    confidence REAL DEFAULT NULL,   -- 0.0-1.0: how sure we are this recommendation is right for this customer (distinct from revenue_score / deal size). See app/agents/confidence.py.
    estimated_deal_value REAL,
    renewal_date DATE,
    generated_at TIMESTAMP,
    agent_trace TEXT,
    outcome TEXT DEFAULT NULL,   -- NULL, 'accepted', 'rejected', 'converted'
    no_recommendation_reason_code TEXT DEFAULT NULL   -- NULL when recommended_product is set; else 'signal_rejected', 'no_opportunity_found', 'critic_vetoed', or 'high_churn_gate'
);

-- Registry of columns a tenant's data has that don't match a known core
-- field. Populated by app/schema_mapping.py's discovery step at ingestion
-- time (LLM-classified), and read by the pipeline/agents at runtime so new
-- columns get considered in profile-creation/reasoning instead of silently
-- dropped or blocking ingestion.
CREATE TABLE IF NOT EXISTS dynamic_field_registry (
    tenant_id TEXT,
    dataset_type TEXT,      -- 'customers' | 'usage_metrics' | 'support_tickets' | 'product_catalog'
    field_name TEXT,        -- key inside extra_attributes JSON (== source_column, normalized)
    source_column TEXT,     -- tenant's original column name exactly as uploaded
    inferred_type TEXT,     -- 'numeric' | 'categorical' | 'date' | 'text' | 'boolean'
    semantic_role TEXT,     -- short LLM-assigned label, e.g. 'engagement_signal', 'contract_detail'
    description TEXT,       -- LLM-written explanation of what this field represents
    example_values TEXT,    -- JSON array of a few sample values, for grounding/debugging
    relevance TEXT,         -- 'profile_creation' | 'churn_signal' | 'deal_scoring' | 'ignore'
    confidence REAL,        -- classifier's confidence this is genuinely new (not a mis-mapped core field)
    discovered_at TIMESTAMP,
    PRIMARY KEY (tenant_id, dataset_type, field_name)
);

-- ---------------------------------------------------------------------------
-- Schema-free ingestion model (see schema_free_pipeline_design.md).
-- Replaces the fixed customers/usage_metrics/support_tickets/product_catalog
-- tables as the source of truth for NEW tenants. Old tables above are kept
-- for backward compatibility / migration only.
-- ---------------------------------------------------------------------------

-- One row per uploaded file. schema_version is a hash of the column list +
-- dtypes, used to detect "this file changed, re-run Stage 1/2" on re-upload.
CREATE TABLE IF NOT EXISTS tenant_datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    dataset_label TEXT NOT NULL,        -- content-inferred, e.g. "customers", "nps_survey"
    original_filename TEXT,
    row_count INTEGER,
    join_key_column TEXT,               -- column that joins this dataset back to a customer entity, if any
    schema_version TEXT,                -- hash of columns+dtypes at last discovery run
    discovered_at TIMESTAMP,
    UNIQUE (tenant_id, original_filename)
);

-- Full column catalog from Stage 1 -- every column, not just leftovers.
CREATE TABLE IF NOT EXISTS tenant_schema_columns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    dataset_id INTEGER NOT NULL,
    column_name TEXT NOT NULL,           -- raw name as uploaded
    inferred_label TEXT,
    description TEXT,
    dtype TEXT,                          -- identifier | numeric | categorical | date | boolean | free_text
    semantic_role TEXT,                  -- entity_id | join_key | metric | dimension | narrative | noise
    relevance TEXT,                      -- high | medium | low | unknown
    concept TEXT,                        -- closed vocabulary, or NULL -- see schema_discovery.py CONCEPTS
    stats_json TEXT,                     -- cheap pandas stats used as Stage 1 input (dtype, null%, distinct, min/max, samples)
    FOREIGN KEY (dataset_id) REFERENCES tenant_datasets(id),
    UNIQUE (tenant_id, dataset_id, column_name)
);

-- Raw rows kept as JSON, resolved against a customer entity where a join
-- key was found. Replaces per-dataset fixed tables for schema-free tenants.
CREATE TABLE IF NOT EXISTS tenant_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    dataset_id INTEGER NOT NULL,
    entity_id TEXT,                      -- resolved customer id, NULL if no join key found for this dataset
    row_json TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES tenant_datasets(id)
);
CREATE INDEX IF NOT EXISTS idx_tenant_records_lookup ON tenant_records(tenant_id, dataset_id, entity_id);

-- Compiled, cached Stage-2 output. One row per tenant. Re-generated only
-- when re-triggered by a dataset schema_version change (see schema_discovery.py).
CREATE TABLE IF NOT EXISTS tenant_prompt_specs (
    tenant_id TEXT PRIMARY KEY,
    prompt_spec TEXT NOT NULL,          -- the tenant-specific instruction block (Stage 2 output)
    possible_insight_categories TEXT,   -- JSON array
    excluded_insight_categories TEXT,   -- JSON array with reasons
    schema_fingerprint TEXT,            -- hash of all dataset schema_versions this was compiled from
    compiled_at TIMESTAMP
);

-- Unresolved data gaps from Stage 3's bounded self-correction loop --
-- concepts the sample-run Signal Agent flagged as missing/low-confidence
-- that re-examination (schema_discovery.reexamine_concept) still couldn't
-- resolve within the iteration cap. Distinct from _data_gaps() in
-- web_api.py, which only detects whole datasets never uploaded -- this is
-- concept-level and schema-free-pipeline-specific.
CREATE TABLE IF NOT EXISTS tenant_schema_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    concept TEXT,                 -- concept name, or NULL for a free-form flag
    flag_type TEXT,                -- 'missing_concept' | 'low_confidence'
    detail TEXT,                   -- the agent's own explanation
    sample_customers TEXT,         -- JSON array of entity_ids this was observed for
    resolved BOOLEAN DEFAULT 0,
    recorded_at TIMESTAMP
);

-- Authorization: one row per company (tenant).
-- A request must present the
-- correct api_key for the tenant_id it's asking about, or it's rejected --
-- see app/auth.py. api_key stores a salted hash, never the raw key.
CREATE TABLE IF NOT EXISTS tenant_api_keys (
    tenant_id TEXT PRIMARY KEY,
    api_key_hash TEXT NOT NULL,
    company_name TEXT,
    created_at TIMESTAMP,
    revoked BOOLEAN DEFAULT 0
);

-- Self-service signup credentials. Separate from tenant_api_keys
-- deliberately: tenant_api_keys is the internal per-session bearer token
-- every request is actually authorized with (see app/auth.py) -- unchanged
-- by this table. tenant_accounts is the human-facing identity layer login
-- checks BEFORE handing out a fresh api_key -- see app/accounts.py.
CREATE TABLE IF NOT EXISTS tenant_accounts (
    tenant_id TEXT PRIMARY KEY,
    client_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenant_api_keys(tenant_id)
);

-- ---------------------------------------------------------------------------
-- Universal Dataset Analyzer tables (domain-agnostic upsell/cross-sell).
-- Supports any dataset shape: e-commerce product data, SaaS CRM, retail
-- transactions, etc. The product_relationships table is the backbone of
-- the product graph used for recommendation scoring.
-- ---------------------------------------------------------------------------

-- Product relationship graph edges (co-purchase, co-view, upsell, etc.)
CREATE TABLE IF NOT EXISTS product_relationships (
    tenant_id TEXT NOT NULL,
    source_product_id TEXT NOT NULL,
    target_product_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,  -- 'bought_together', 'also_bought', 'also_viewed',
                                      -- 'buy_after_viewing', 'same_category_upgrade', 'complementary'
    weight REAL DEFAULT 1.0,          -- co-occurrence frequency or computed strength
    PRIMARY KEY (tenant_id, source_product_id, target_product_id, relationship_type)
);
CREATE INDEX IF NOT EXISTS idx_product_rel_source ON product_relationships(tenant_id, source_product_id);
CREATE INDEX IF NOT EXISTS idx_product_rel_target ON product_relationships(tenant_id, target_product_id);

-- Upsell/cross-sell opportunity predictions (universal, domain-agnostic)
CREATE TABLE IF NOT EXISTS upsell_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    source_product_id TEXT NOT NULL,
    target_product_id TEXT NOT NULL,
    prediction_type TEXT NOT NULL,    -- 'upsell', 'cross_sell', 'bundle'
    score REAL,                       -- 0-100 opportunity score
    confidence REAL,                  -- 0.0-1.0 confidence
    source_product_title TEXT,
    target_product_title TEXT,
    rationale TEXT,
    evidence_json TEXT,               -- JSON of supporting signals
    generated_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_upsell_pred_tenant ON upsell_predictions(tenant_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_upsell_pred_source ON upsell_predictions(tenant_id, source_product_id);

-- Dataset analysis results (domain detection, signal summary)
CREATE TABLE IF NOT EXISTS dataset_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    domain TEXT,                      -- 'ecommerce', 'saas', 'retail_transaction', 'generic'
    analysis_summary TEXT,
    signal_counts_json TEXT,          -- JSON of signal type -> count
    total_products INTEGER,
    total_relationships INTEGER,
    total_predictions INTEGER,
    top_opportunities_json TEXT,      -- JSON of top N predictions for quick access
    analyzed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dataset_analysis_tenant ON dataset_analyses(tenant_id);
