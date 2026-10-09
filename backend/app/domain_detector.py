"""
Domain Detector – classifies the business domain of an uploaded dataset.

Supported domains:
    * **ecommerce** – Amazon-style product / review data
    * **saas** – subscription / usage-based SaaS metrics
    * **retail_transaction** – in-store / POS basket data
    * **generic** – fallback when no strong signal is found

Detection works by matching normalised column names (and optionally
descriptions / concepts from the schema catalog) against curated keyword
signal sets.  A confidence score is computed as the fraction of signal
keywords matched for the winning domain.

The companion ``get_domain_analysis_config`` function returns a
domain-specific configuration dict that downstream agents can use to
locate important fields (IDs, prices, categories, …).
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from app.logging_config import get_logger
from app import db

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

DOMAIN_ECOMMERCE = "ecommerce"
DOMAIN_SAAS = "saas"
DOMAIN_RETAIL = "retail_transaction"
DOMAIN_GENERIC = "generic"

# ---------------------------------------------------------------------------
# Signal keyword sets – each keyword is checked via *substring* match
# against the normalised column name.
# ---------------------------------------------------------------------------

ECOMMERCE_SIGNALS: set[str] = {
    "asin",
    "product",
    "review",
    "rating",
    "price",
    "brand",
    "category",
    "also_bought",
    "bought_together",
    "also_viewed",
    "buy_after_viewing",
    "verified_purchase",
    "helpful_vote",
    "parent_asin",
    "main_category",
}

SAAS_SIGNALS: set[str] = {
    "renewal_date",
    "seats",
    "plan_tier",
    "storage",
    "active_users",
    "feature_usage",
    "support_ticket",
    "nps",
    "csat",
    "churn",
    "mrr",
    "contract",
}

RETAIL_SIGNALS: set[str] = {
    "transaction",
    "basket",
    "quantity",
    "receipt",
    "store",
    "sku",
    "upc",
    "barcode",
    "checkout",
}

# Mapping from domain constant → signal set for iteration.
_DOMAIN_SIGNALS: dict[str, set[str]] = {
    DOMAIN_ECOMMERCE: ECOMMERCE_SIGNALS,
    DOMAIN_SAAS: SAAS_SIGNALS,
    DOMAIN_RETAIL: RETAIL_SIGNALS,
}

# ---------------------------------------------------------------------------
# Filename hint → domain boost mapping
# ---------------------------------------------------------------------------

_FILENAME_HINTS: dict[str, str] = {
    "amazon": DOMAIN_ECOMMERCE,
    "review": DOMAIN_ECOMMERCE,
    "product": DOMAIN_ECOMMERCE,
    "transaction": DOMAIN_RETAIL,
    "saas": DOMAIN_SAAS,
}

# =========================================================================
# Core detection helpers
# =========================================================================


def _normalise_columns(columns: list[str]) -> list[str]:
    """Lower-case, strip whitespace, replace spaces / hyphens with ``_``."""
    normed: list[str] = []
    for col in columns:
        c = col.strip().lower()
        c = re.sub(r"[\s\-]+", "_", c)
        normed.append(c)
    return normed


def _count_signal_matches(
    normed_columns: list[str],
    signals: set[str],
) -> dict[str, list[str]]:
    """Return a mapping of *signal keyword* → list of columns that matched.

    A column matches a signal if the signal appears as a substring of the
    normalised column name.
    """
    matches: dict[str, list[str]] = {}
    for signal in signals:
        for col in normed_columns:
            if signal in col:
                matches.setdefault(signal, []).append(col)
    return matches


# =========================================================================
# Public API
# =========================================================================


def detect_domain_from_columns(
    columns: list[str],
    stats: dict | None = None,
) -> dict[str, Any]:
    """Classify domain by examining column names.

    Parameters
    ----------
    columns:
        Raw column names from the uploaded dataset.
    stats:
        Optional per-column statistics (currently unused but reserved for
        future heuristic enrichment).

    Returns
    -------
    dict with keys ``domain``, ``confidence``, ``signal_matches``,
    ``details``.
    """
    normed = _normalise_columns(columns)
    log.info("Detecting domain from %d columns", len(normed))

    best_domain = DOMAIN_GENERIC
    best_count = 0
    best_confidence = 0.0
    all_matches: dict[str, dict[str, list[str]]] = {}

    for domain, signals in _DOMAIN_SIGNALS.items():
        matches = _count_signal_matches(normed, signals)
        match_count = len(matches)
        all_matches[domain] = matches

        if match_count > best_count:
            best_count = match_count
            best_domain = domain
            best_confidence = match_count / len(signals)

    if best_count == 0:
        log.info("No domain signals matched – falling back to '%s'", DOMAIN_GENERIC)
        return {
            "domain": DOMAIN_GENERIC,
            "confidence": 0.0,
            "signal_matches": {},
            "details": "No domain-specific signals found in column names.",
        }

    details = (
        f"Detected domain '{best_domain}' with {best_count} signal keyword(s) "
        f"matched out of {len(_DOMAIN_SIGNALS[best_domain])} "
        f"(confidence {best_confidence:.2%})."
    )
    log.info(details)

    return {
        "domain": best_domain,
        "confidence": round(best_confidence, 4),
        "signal_matches": all_matches[best_domain],
        "details": details,
    }


def detect_domain_from_schema_catalog(tenant_id: str) -> dict[str, Any]:
    """Detect domain using the tenant's persisted schema catalog.

    Pulls every column row from ``tenant_schema_columns`` (via
    :pyfunc:`db.get_tenant_schema_catalog`) and feeds column names,
    descriptions, and concept tags through the signal matcher.

    Parameters
    ----------
    tenant_id:
        The tenant whose schema catalog should be inspected.

    Returns
    -------
    dict  – same shape as :pyfunc:`detect_domain_from_columns`.
    """
    catalog_rows = db.get_tenant_schema_catalog(tenant_id)

    if not catalog_rows:
        log.warning("No schema catalog found for tenant %s", tenant_id)
        return {
            "domain": DOMAIN_GENERIC,
            "confidence": 0.0,
            "signal_matches": {},
            "details": "Schema catalog is empty – cannot detect domain.",
        }

    # Gather column names
    col_names: list[str] = [
        r.get("original_name") or r.get("column_name", "")
        for r in catalog_rows
    ]

    # Gather descriptions and concepts as extra "pseudo-columns" for matching
    extras: list[str] = []
    for r in catalog_rows:
        desc = r.get("description", "") or ""
        concept = r.get("concept", "") or ""
        if desc:
            extras.append(desc)
        if concept:
            extras.append(concept)

    # Primary detection on real column names
    primary = detect_domain_from_columns(col_names)

    # Secondary pass on descriptions / concepts
    normed_extras = _normalise_columns(extras)
    extra_matches_by_domain: dict[str, int] = {}
    for domain, signals in _DOMAIN_SIGNALS.items():
        extra_matches = _count_signal_matches(normed_extras, signals)
        extra_matches_by_domain[domain] = len(extra_matches)

    # Combine: if extra evidence strengthens a different domain, consider it
    combined_domain = primary["domain"]
    combined_confidence = primary["confidence"]

    for domain, extra_count in extra_matches_by_domain.items():
        if extra_count == 0:
            continue
        total_signals = len(_DOMAIN_SIGNALS[domain])
        primary_count = len(primary["signal_matches"]) if domain == primary["domain"] else 0
        combined_count = primary_count + extra_count
        combined_conf = combined_count / total_signals

        if combined_conf > combined_confidence:
            combined_domain = domain
            combined_confidence = combined_conf

    combined_confidence = min(combined_confidence, 1.0)

    details = (
        f"Schema-catalog detection for tenant '{tenant_id}': "
        f"domain='{combined_domain}', confidence={combined_confidence:.2%}."
    )
    log.info(details)

    return {
        "domain": combined_domain,
        "confidence": round(combined_confidence, 4),
        "signal_matches": primary["signal_matches"],
        "details": details,
    }


def detect_domain_from_dataframe(
    df: pd.DataFrame,
    filename_hint: str | None = None,
) -> dict[str, Any]:
    """Detect domain from a pandas DataFrame.

    Uses column names as the primary signal.  If *filename_hint* is
    provided and contains a recognised keyword (e.g. ``'amazon'``,
    ``'transaction'``), the corresponding domain receives a small
    confidence boost.

    Parameters
    ----------
    df:
        The uploaded DataFrame.
    filename_hint:
        Original filename (or a fragment) to use for hint-based boosting.

    Returns
    -------
    dict  – same shape as :pyfunc:`detect_domain_from_columns`.
    """
    columns = list(df.columns.astype(str))

    # Optionally incorporate unique string values from each column as extra
    # signal sources (e.g. a column named 'type' whose values include
    # "subscription" would nudge towards SaaS).
    sample_values: list[str] = []
    for col in df.columns:
        try:
            uniques = df[col].dropna().unique()[:10]
            sample_values.extend(str(v) for v in uniques)
        except Exception:
            pass

    result = detect_domain_from_columns(columns)

    # Filename hint boost
    if filename_hint:
        fn_lower = filename_hint.lower()
        for hint_keyword, hint_domain in _FILENAME_HINTS.items():
            if hint_keyword in fn_lower:
                boost = 0.10
                if hint_domain == result["domain"]:
                    result["confidence"] = min(round(result["confidence"] + boost, 4), 1.0)
                    result["details"] += (
                        f" Filename hint '{hint_keyword}' reinforced "
                        f"'{hint_domain}' (+{boost:.0%} boost)."
                    )
                elif result["domain"] == DOMAIN_GENERIC:
                    # Promote from generic if filename gives a clear hint
                    result["domain"] = hint_domain
                    result["confidence"] = round(boost, 4)
                    result["details"] = (
                        f"No column signals, but filename hint "
                        f"'{hint_keyword}' suggests '{hint_domain}'."
                    )
                log.info(
                    "Filename hint '%s' applied – domain=%s, confidence=%.4f",
                    hint_keyword,
                    result["domain"],
                    result["confidence"],
                )
                break  # apply at most one hint

    return result


# =========================================================================
# Domain-specific analysis config
# =========================================================================


def get_domain_analysis_config(domain: str) -> dict[str, Any]:
    """Return a configuration dict tailored for the given *domain*.

    Downstream agents use this to know which candidate field names to look
    for when resolving IDs, prices, categories, etc.

    Parameters
    ----------
    domain:
        One of the ``DOMAIN_*`` constants defined in this module.

    Returns
    -------
    dict  – keys vary by domain but always include ``entity_type`` and
    ``id_field_candidates``.
    """
    configs: dict[str, dict[str, Any]] = {
        DOMAIN_ECOMMERCE: {
            "entity_type": "product",
            "id_field_candidates": [
                "asin", "parent_asin", "product_id", "item_id", "sku",
            ],
            "relationship_fields": [
                "also_bought", "bought_together", "also_viewed",
                "buy_after_viewing",
            ],
            "price_field_candidates": [
                "price", "list_price", "sale_price",
            ],
            "category_field_candidates": [
                "category", "categories", "main_category", "department",
            ],
            "rating_field_candidates": [
                "rating", "overall", "score", "stars", "average_rating",
            ],
            "text_field_candidates": [
                "review_text", "text", "description", "title", "summary",
            ],
        },
        DOMAIN_SAAS: {
            "entity_type": "customer",
            "id_field_candidates": [
                "customer_id", "account_id", "client_id",
            ],
            "contract_field_candidates": [
                "contract_start", "contract_end", "renewal_date",
                "contract_value",
            ],
            "plan_field_candidates": [
                "plan_tier", "plan_name", "subscription_type",
            ],
            "usage_field_candidates": [
                "active_users", "seats", "storage_used_gb",
                "storage_limit_gb", "feature_usage", "usage_trend_metric",
            ],
            "revenue_field_candidates": [
                "mrr", "arr", "price_per_seat", "monthly_revenue",
            ],
            "health_field_candidates": [
                "nps", "csat", "churn", "support_ticket",
                "ticket_severity",
            ],
        },
        DOMAIN_RETAIL: {
            "entity_type": "transaction",
            "id_field_candidates": [
                "transaction_id", "receipt_id", "order_id", "basket_id",
            ],
            "product_field_candidates": [
                "sku", "upc", "barcode", "product_id", "item_id",
            ],
            "quantity_field_candidates": [
                "quantity", "qty", "units",
            ],
            "price_field_candidates": [
                "price", "unit_price", "total_price", "amount",
            ],
            "store_field_candidates": [
                "store", "store_id", "location", "branch",
            ],
            "datetime_field_candidates": [
                "transaction_date", "checkout_time", "date", "timestamp",
            ],
        },
        DOMAIN_GENERIC: {
            "entity_type": "record",
            "id_field_candidates": [
                "id", "record_id", "key", "uuid",
            ],
            "name_field_candidates": [
                "name", "title", "label", "description",
            ],
            "date_field_candidates": [
                "date", "created_at", "updated_at", "timestamp",
            ],
            "numeric_field_candidates": [
                "amount", "value", "count", "total", "score",
            ],
            "category_field_candidates": [
                "type", "category", "status", "group",
            ],
        },
    }

    config = configs.get(domain, configs[DOMAIN_GENERIC])
    log.debug("Analysis config for domain '%s': %s", domain, list(config.keys()))
    return config


# =========================================================================
# CLI quick-test
# =========================================================================

if __name__ == "__main__":
    # Quick smoke test with synthetic column lists
    print("=" * 60)
    print("Domain Detector – smoke test")
    print("=" * 60)

    ecom_cols = [
        "parent_asin", "Product Title", "price", "Brand",
        "main_category", "rating", "also_bought", "review_text",
    ]
    print("\n--- E-commerce columns ---")
    result = detect_domain_from_columns(ecom_cols)
    print(f"  Domain : {result['domain']}")
    print(f"  Conf.  : {result['confidence']}")
    print(f"  Details: {result['details']}")

    saas_cols = [
        "customer_id", "renewal_date", "seats", "plan_tier",
        "active_users", "storage_used_gb", "mrr", "nps",
    ]
    print("\n--- SaaS columns ---")
    result = detect_domain_from_columns(saas_cols)
    print(f"  Domain : {result['domain']}")
    print(f"  Conf.  : {result['confidence']}")
    print(f"  Details: {result['details']}")

    retail_cols = [
        "transaction_id", "store_id", "sku", "quantity",
        "unit_price", "checkout_time", "receipt_no",
    ]
    print("\n--- Retail columns ---")
    result = detect_domain_from_columns(retail_cols)
    print(f"  Domain : {result['domain']}")
    print(f"  Conf.  : {result['confidence']}")
    print(f"  Details: {result['details']}")

    generic_cols = ["col_a", "col_b", "col_c"]
    print("\n--- Generic columns ---")
    result = detect_domain_from_columns(generic_cols)
    print(f"  Domain : {result['domain']}")
    print(f"  Conf.  : {result['confidence']}")
    print(f"  Details: {result['details']}")

    # DataFrame detection with filename hint
    print("\n--- DataFrame + filename hint ---")
    df = pd.DataFrame({"item": [1], "score": [5], "text": ["good"]})
    result = detect_domain_from_dataframe(df, filename_hint="amazon_reviews.csv")
    print(f"  Domain : {result['domain']}")
    print(f"  Conf.  : {result['confidence']}")
    print(f"  Details: {result['details']}")

    # Config look-up
    print("\n--- Analysis config for 'ecommerce' ---")
    cfg = get_domain_analysis_config(DOMAIN_ECOMMERCE)
    for k, v in cfg.items():
        print(f"  {k}: {v}")

    print("\nDone.")
