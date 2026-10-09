"""
Schema Mapping — solves the "different tenants have differently-named
columns" problem. Not exposed over HTTP; used as a library by whatever
loader script writes tenant data into the SQL database (see
app/data_ingestion.py). This module:

  1. Suggests a best-guess mapping from a tenant's raw columns to our
     internal schema, using fuzzy string matching (no LLM required), plus
     an optional IndiaAI call for names too different for string
     similarity to catch.
  2. Classifies genuinely new columns (that aren't a known field under a
     different name) via discover_unmapped_columns(), storing what an LLM
     inferred about them in dynamic_field_registry, so a tenant-specific
     column can be considered by the recommendation logic without any
     per-tenant code.

Covers all four datasets: customers, usage_metrics, support_tickets,
product_catalog. Each dataset's mapping and discovered fields are
independent -- a wrong or missing mapping on one dataset never blocks or
corrupts another.
"""

import json
from difflib import get_close_matches

import pandas as pd
from app import db
from app.config import LLM_MODEL
from app.indiaai_client import is_configured
from app.indiaai_client import make_client
from app.logging_config import get_logger

log = get_logger(__name__)

# The fields the rest of the pipeline actually needs per dataset, regardless
# of what the tenant calls them in their own system. `required=False` fields
# are nice-to-have -- validate_mapping() won't block confirmation on them.
FIELD_DEFINITIONS = {
    "customers": {
        "customer_id": ("Unique identifier for the customer", True),
        "customer_name": ("Customer / company name", True),
        "plan_tier": ("Current subscription plan or tier", True),
        "seats": ("Number of seats / licenses", True),
        "renewal_date": ("Contract or subscription renewal date", True),
        "industry": ("Customer's industry (optional)", False),
    },
    "usage_metrics": {
        "customer_id": ("Unique identifier for the customer", True),
        "month": ("Month this usage snapshot covers", True),
        # active_users/storage_*_gb are SaaS-specific concepts (seat counts,
        # storage quotas) -- they don't generalize to every tenant's
        # business (e.g. a physical-goods retailer has no "storage limit").
        # Marking these required=True used to force the schema mapper to
        # match SOME column onto them even for tenants with no such
        # concept at all, which is how a badminton-gear tenant ended up
        # with fabricated GB-storage figures narrated in its churn
        # analysis. required=False lets a tenant genuinely have none of
        # these -- see _bandwidth()/storage_pct_used(), which now treat
        # their absence as "not applicable" rather than defaulting to 0.
        "active_users": ("Count of active users that month (optional -- SaaS-specific)", False),
        "storage_used_gb": ("Storage used, in GB (optional -- SaaS-specific)", False),
        "storage_limit_gb": ("Storage limit/quota, in GB (optional -- SaaS-specific)", False),
        "feature_usage_score": ("Aggregate feature usage score (0-100) -- optional, derived "
                                "from per-service usage if not provided", False),
    },
    "support_tickets": {
        "ticket_id": ("Unique identifier for the support ticket", True),
        "customer_id": ("Unique identifier for the customer", True),
        "created_at": ("Date the ticket was created", True),
        "category": ("Ticket category, e.g. security/technical/billing", True),
        "subject": ("Ticket subject / short description", True),
        "resolved": ("Whether the ticket has been resolved (true/false)", True),
    },
    "product_catalog": {
        "product_id": ("Unique identifier for the product", True),
        "product_name": ("Product display name", True),
        "tier_level": ("Numeric tier level (higher = more advanced plan)", True),
        "price_per_seat": ("Price per seat, monthly", True),
        "complements": ("Related/complementary product name(s) (optional)", False),
        "category": ("Product category, improves matching (optional)", False),
        "description": ("Product description, improves matching (optional)", False),
    },
}

# Common aliases to seed the fuzzy matcher with better guesses than pure
# string similarity alone would produce, per dataset.
KNOWN_ALIASES = {
    "customers": {
        "customer_id": ["cust_id", "account_id", "client_id", "id"],
        "customer_name": ["company", "account_name", "client_name", "name"],
        "plan_tier": ["plan", "subscription_tier", "tier", "package"],
        "seats": ["num_seats", "licenses", "user_count", "seat_count"],
        "renewal_date": ["contract_end", "expiry_date", "renewaldt", "end_date"],
        "industry": ["sector", "vertical", "industry_type"],
    },
    "usage_metrics": {
        "customer_id": ["cust_id", "account_id", "client_id", "id"],
        "month": ["usage_month", "period", "reporting_month", "date"],
        "active_users": ["mau", "active_user_count", "users_active", "num_active_users"],
        "storage_used_gb": ["storage_used", "used_storage_gb", "storage_gb_used", "gb_used"],
        "storage_limit_gb": ["storage_limit", "storage_quota_gb", "storage_cap_gb", "gb_limit"],
        "feature_usage_score": ["usage_score", "engagement_score", "feature_score", "adoption_score"],
    },
    "support_tickets": {
        "ticket_id": ["ticket_number", "case_id", "issue_id", "id"],
        "customer_id": ["cust_id", "account_id", "client_id", "id"],
        "created_at": ["date_created", "opened_at", "created_date", "open_date"],
        "category": ["ticket_category", "type", "issue_type"],
        "subject": ["ticket_subject", "title", "summary", "description"],
        "resolved": ["is_resolved", "closed", "status_resolved", "resolved_flag"],
    },
    "product_catalog": {
        "product_id": ["sku", "item_id", "product_code", "id"],
        "product_name": ["name", "product", "item_name"],
        "tier_level": ["tier", "plan_level", "level"],
        "price_per_seat": ["price", "seat_price", "unit_price", "price_per_user"],
        "complements": ["related_products", "bundled_with", "complementary_products"],
        "category": ["product_category", "type", "family"],
        "description": ["desc", "product_description", "summary"],
    },
}


def _required_fields(dataset_type: str) -> dict:
    return {f: desc for f, (desc, required) in FIELD_DEFINITIONS[dataset_type].items()}


def suggest_column_mapping_llm(source_columns: list[str], dataset_type: str = "customers") -> dict | None:
    """
    LLM-based mapping suggestion. Handles cases pure string-similarity can't:
    abbreviations, non-English headers, semantically-related but textually
    dissimilar names (e.g. 'MRR_Seats_Active' -> seats).

    Returns None (never raises) if the LLM call fails or returns something
    unusable -- the caller falls back to fuzzy matching. This mirrors the
    _AgentWithFallback pattern used elsewhere in the pipeline: an LLM step
    degrading to a deterministic default rather than breaking onboarding.
    """
    if not is_configured():
        return None
    field_definitions = FIELD_DEFINITIONS[dataset_type]
    try:
        client = make_client()
        field_desc = "\n".join(f"- {f}: {desc}" for f, (desc, _required) in field_definitions.items())
        prompt = (
            f"Map each of the tenant's source columns from their '{dataset_type}' "
            "file to the internal field it represents, if any. Internal fields:\n"
            f"{field_desc}\n\n"
            f"Tenant's source columns: {json.dumps(source_columns)}\n\n"
            "Return ONLY a JSON object with exactly these keys: "
            f"{json.dumps(list(field_definitions.keys()))}. "
            "Each value must be either one of the exact source column strings "
            "given above, or null if nothing matches. No two internal fields "
            "may map to the same source column. Return nothing but the JSON object."
        )
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = json.loads(resp.choices[0].message.content)
    except Exception as e:
        log.warning(
            "LLM column-mapping suggestion for '%s' failed (%s) -- falling back to fuzzy match.",
            dataset_type, e,
        )
        return None

    # Validate shape defensively -- never trust the model's output structurally.
    mapping = {}
    seen_source_cols = set()
    for field in field_definitions:
        val = raw.get(field)
        if val is not None and (val not in source_columns or val in seen_source_cols):
            val = None  # hallucinated a column that doesn't exist, or reused one
        if val is not None:
            seen_source_cols.add(val)
        mapping[field] = val
    return mapping


def suggest_column_mapping(source_columns: list[str], dataset_type: str = "customers") -> dict:
    """
    Returns a best-guess mapping: {internal_field: suggested_source_column or None}.
    This is a SUGGESTION only — never used without user confirmation.

    Runs in two passes so two internal fields can never both claim the same
    source column (e.g. a ticket file with both a 'Case_ID' and 'Client_ID'
    column, where 'ticket_id' and 'customer_id' are both aliased near "*_id"
    and could otherwise steal each other's correct match via fuzzy string
    similarity alone):

      Pass 1 -- exact (case/space-insensitive) matches against a field's own
      name or one of its KNOWN_ALIASES. These are unambiguous, so they're
      resolved first and those source columns are taken off the table.

      Pass 2 -- fuzzy matching (difflib) for whatever's left, restricted to
      source columns no other field has already claimed.
    """
    normalized_source = {c.lower().replace(" ", "_"): c for c in source_columns}
    aliases = KNOWN_ALIASES.get(dataset_type, {})
    fields = list(FIELD_DEFINITIONS[dataset_type])

    suggestions = {field: None for field in fields}
    claimed_keys: set[str] = set()

    # Pass 1: exact alias/name matches, claimed first.
    for field in fields:
        candidates = [field] + aliases.get(field, [])
        for candidate in candidates:
            if candidate in normalized_source and candidate not in claimed_keys:
                suggestions[field] = normalized_source[candidate]
                claimed_keys.add(candidate)
                break

    # Pass 2: fuzzy fallback for anything pass 1 didn't resolve, restricted
    # to source columns nothing else has claimed yet.
    for field in fields:
        if suggestions[field] is not None:
            continue
        candidates = [field] + aliases.get(field, [])
        available_keys = [k for k in normalized_source if k not in claimed_keys]
        match_key = None
        for candidate in candidates:
            close = get_close_matches(candidate, available_keys, n=1, cutoff=0.6)
            if close:
                match_key = close[0]
                break
        if match_key:
            suggestions[field] = normalized_source[match_key]
            claimed_keys.add(match_key)

    return suggestions


def save_column_mapping(tenant_id: str, dataset_type: str, mapping: dict, confirmed: bool = True) -> None:
    """Persists the (user-confirmed) mapping for this tenant + dataset."""
    conn = db.get_connection()
    cur = conn.cursor()
    for internal_field, source_column in mapping.items():
        if source_column is None:
            continue
        cur.execute(
            """INSERT OR REPLACE INTO column_mappings
               (tenant_id, dataset_type, internal_field, source_column, confirmed_by_user)
               VALUES (?, ?, ?, ?, ?)""",
            (tenant_id, dataset_type, internal_field, source_column, confirmed),
        )
    conn.commit()
    conn.close()


def get_column_mapping(tenant_id: str, dataset_type: str = "customers") -> dict:
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT internal_field, source_column FROM column_mappings "
        "WHERE tenant_id = ? AND dataset_type = ?",
        (tenant_id, dataset_type),
    )
    rows = cur.fetchall()
    conn.close()
    return {r["internal_field"]: r["source_column"] for r in rows}


def is_mapping_confirmed(tenant_id: str, dataset_type: str) -> bool:
    """
    True once every required field for this dataset has a confirmed
    (confirmed_by_user=1) mapping on file for this tenant. Checked per
    dataset -- confirming `customers` never counts as confirming
    `usage_metrics`, `support_tickets`, or `product_catalog`.
    """
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT internal_field FROM column_mappings "
        "WHERE tenant_id = ? AND dataset_type = ? AND confirmed_by_user = 1",
        (tenant_id, dataset_type),
    )
    confirmed_fields = {r["internal_field"] for r in cur.fetchall()}
    conn.close()

    required = {f for f, (_desc, req) in FIELD_DEFINITIONS[dataset_type].items() if req}
    return required.issubset(confirmed_fields)


def validate_mapping(mapping: dict, dataset_type: str = "customers") -> list[str]:
    """
    Returns a list of problems found in the mapping, surfaced to the user
    before they can proceed past onboarding:
      - missing required fields (no source column found)
      - duplicate mappings (two internal fields pointing at the same source
        column) -- this happens with ambiguous auto-suggestions and must be
        caught, since it would silently corrupt one of the two fields.
    """
    problems = []
    field_definitions = FIELD_DEFINITIONS[dataset_type]

    missing = [
        f for f, (_desc, required) in field_definitions.items()
        if required and mapping.get(f) is None
    ]
    problems.extend(f"missing mapping for required field: {f}" for f in missing)

    seen = {}
    for field, source_col in mapping.items():
        if source_col is None:
            continue
        if source_col in seen:
            problems.append(
                f"duplicate mapping: both '{seen[source_col]}' and '{field}' "
                f"are mapped to source column '{source_col}'"
            )
        else:
            seen[source_col] = field

    return problems


def apply_mapping(raw_df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """
    Renames the tenant's raw columns to our internal schema names.
    Only renames columns that are actually present in the mapping AND the dataframe,
    so it won't crash on partial/optional fields.
    """
    rename_map = {
        source_col: internal_field
        for internal_field, source_col in mapping.items()
        if source_col is not None and source_col in raw_df.columns
    }
    return raw_df.rename(columns=rename_map)


def onboard_tenant(
    tenant_id: str, sample_columns: list[str], use_llm: bool = False, dataset_type: str = "customers"
) -> dict:
    """
    Entry point for a tenant's onboarding flow for ONE dataset (customers,
    usage_metrics, support_tickets, or product_catalog). Returns a suggested
    mapping for the frontend to display for confirmation — does NOT save
    anything until the user explicitly confirms via save_column_mapping().

    use_llm=True tries the LLM-based suggestion first (handles abbreviations,
    non-English headers, or names that are semantically but not textually
    similar). Fuzzy matching always runs too and fills in any field the LLM
    left null or that the LLM call failed to produce -- so a tenant never
    gets a worse result by turning this on, only a chance at a better one.
    `mapping_source` in the response tells the caller, per field, whether
    the LLM or fuzzy matching supplied that guess (or neither).
    """
    if dataset_type not in FIELD_DEFINITIONS:
        raise ValueError(
            f"Unknown dataset_type '{dataset_type}'. Must be one of: {sorted(FIELD_DEFINITIONS)}"
        )

    fuzzy_suggestions = suggest_column_mapping(sample_columns, dataset_type)
    mapping_source = {f: ("fuzzy" if v else None) for f, v in fuzzy_suggestions.items()}

    suggestions = dict(fuzzy_suggestions)
    llm_used = False
    if use_llm:
        llm_suggestions = suggest_column_mapping_llm(sample_columns, dataset_type)
        if llm_suggestions is not None:
            llm_used = True
            for field, val in llm_suggestions.items():
                if val is not None:
                    suggestions[field] = val
                    mapping_source[field] = "llm"

    missing = validate_mapping(suggestions, dataset_type)
    return {
        "tenant_id": tenant_id,
        "dataset_type": dataset_type,
        "suggested_mapping": suggestions,
        "mapping_source": mapping_source,
        "llm_requested": use_llm,
        "llm_used": llm_used,  # False if use_llm was True but the LLM call failed -- fuzzy-only result
        "unmapped_required_fields": missing,
        "required_fields_reference": _required_fields(dataset_type),
    }


def discover_unmapped_columns(
    tenant_id: str, dataset_type: str, sample_columns: list[str],
    mapped_columns: set[str], sample_rows: list[dict] = None,
) -> list[dict]:
    """
    For every uploaded column NOT used by the confirmed core mapping, decide
    whether it's:
      (a) actually one of our known core fields that matching just missed
          (the "mis-mapped" safeguard) -- if so, do NOT register it as new;
          log a warning instead, since this usually means the mapping should
          be revisited, not that a new concept was found, or
      (b) genuinely new -- classify it with an LLM (name, likely type,
          semantic role, whether it's relevant to reasoning) and return it
          for app.db.upsert_dynamic_field() to persist into
          dynamic_field_registry.

    Never blocks ingestion -- on any failure (no API key, call error) columns
    still get returned as 'unclassified' / low confidence so raw values are
    at least preserved in extra_attributes, and can be reclassified later.
    """
    unmapped = [c for c in sample_columns if c not in mapped_columns]
    if not unmapped:
        return []

    field_defs = FIELD_DEFINITIONS.get(dataset_type, {})
    aliases = KNOWN_ALIASES.get(dataset_type, {})
    results = []

    for col in unmapped:
        # (a) Mis-mapped safeguard: does this column actually look like one
        # of our known core fields under a name fuzzy matching didn't catch?
        # Reuse the same close-match logic suggest_column_mapping() uses,
        # against field names AND their aliases, so we don't build a second
        # parallel matching system.
        candidate_names = list(field_defs.keys())
        for field, alias_list in aliases.items():
            candidate_names.extend(alias_list)
        close = get_close_matches(col.lower(), [c.lower() for c in candidate_names], n=1, cutoff=0.82)
        if close:
            log.warning(
                "Column '%s' in tenant '%s' dataset '%s' looks like it might actually be a "
                "known core field (close match found) rather than a new one -- skipping "
                "dynamic-field registration; revisit the column mapping instead.",
                col, tenant_id, dataset_type,
            )
            continue

        # (b) Genuinely new -- classify with the LLM if available.
        examples = []
        if sample_rows:
            examples = [str(r.get(col)) for r in sample_rows[:5] if r.get(col) is not None]

        classification = _classify_new_column_llm(col, dataset_type, examples)
        results.append({
            "tenant_id": tenant_id,
            "dataset_type": dataset_type,
            "field_name": col,
            "source_column": col,
            "inferred_type": classification.get("inferred_type", "text"),
            "semantic_role": classification.get("semantic_role", "unclassified"),
            "description": classification.get("description", f"Tenant-specific column '{col}', not yet classified."),
            "example_values": examples,
            "relevance": classification.get("relevance", "profile_creation"),
            "confidence": classification.get("confidence", 0.3),
        })

    return results


def _classify_new_column_llm(column_name: str, dataset_type: str, example_values: list[str]) -> dict:
    """Best-effort LLM classification of one genuinely-new column. Returns a
    safe default dict on any failure -- caller never blocks on this."""
    default = {
        "inferred_type": "text",
        "semantic_role": "unclassified",
        "description": f"Tenant-specific column '{column_name}' (not yet classified).",
        "relevance": "profile_creation",
        "confidence": 0.3,
    }
    if not is_configured():
        return default
    try:
        client = make_client()
        prompt = f"""A SaaS company's '{dataset_type}' dataset has a column named '{column_name}'
that doesn't match any of our known fields. Example values: {example_values or 'none available'}.

Classify it. Respond ONLY with JSON:
{{
  "inferred_type": "numeric" | "categorical" | "date" | "text" | "boolean",
  "semantic_role": "short label, e.g. engagement_signal, contract_detail, risk_indicator, internal_note",
  "description": "one sentence describing what this column likely represents",
  "relevance": "profile_creation" | "churn_signal" | "deal_scoring" | "ignore",
  "confidence": float between 0 and 1
}}"""
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return {**default, **result}
    except Exception as e:
        log.warning("LLM classification failed for new column '%s' (%s) -- storing unclassified.",
                    column_name, e)
        return default
