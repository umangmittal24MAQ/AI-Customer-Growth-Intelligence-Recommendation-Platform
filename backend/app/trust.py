"""Deterministic, conservative eligibility and auditable source excerpts.

Product category is a business boundary, NOT an embedding similarity.
Unknown/incomplete mappings abstain instead of guessing a different vertical.
"""
from __future__ import annotations
import os
import re

STOPWORDS = {"plan", "tier", "product", "starter", "premium", "standard", "plus", "advanced", "pro", "bundle", "add", "on", "the", "for", "with", "and"}


def _tokens(value):
    return {w for w in re.findall(r"[a-z0-9]+", str(value or "").lower()) if len(w) >= 3 and w not in STOPWORDS}


def eligible_catalog(catalog: list[dict], customer: dict, signals: dict, max_items: int = 7):
    """Prefer within-product-family upgrades and *explicitly signaled* add-ons.

    Catalog metadata not present? Preserve abstention, do not guess.
    """
    current_name = str(customer.get("plan_tier") or "")
    current = next((p for p in catalog if str(p.get("product_name", "")).casefold() == current_name.casefold()), None)
    if current is None:
        return [], "unknown_current_product"
    category = str(current.get("category") or "").strip().casefold()
    current_tokens = _tokens(current_name)
    try:
        current_tier = int(current.get("tier_level") or 0)
    except (ValueError, TypeError):
        current_tier = 0
    complements = {s.strip().casefold() for s in str(current.get("complements") or current.get("cross_sell") or "").split(",") if s.strip()}
    # Only customer-provided evidence: never catalog descriptions as proof of demand.
    signal_text = " ".join(str(v) for key, value in signals.items() if key in
        ("tickets", "usage_rows", "dynamic_fields", "usage_dynamic_fields", "ticket_dynamic_fields") for v in [value]).lower()
    ranked = []
    for item in catalog:
        name = str(item.get("product_name") or "")
        if not name or name.casefold() == current_name.casefold():
            continue
        item_cat = str(item.get("category") or "").strip().casefold()
        try:
            tier = int(item.get("tier_level") or 0)
        except (ValueError, TypeError):
            tier = 0
        upgrade = bool(category and category == item_cat and current_tier and tier == current_tier + 1)
        explicit_complement = name.casefold() in complements
        # Add-ons need both a catalog category and a supporting customer signal.
        category_tokens = _tokens(item_cat)
        explicitly_needed = (item_cat not in ("", category, "core", "core-plan", "plan")
            and bool(category_tokens) and category_tokens.issubset(_tokens(signal_text)))
        if upgrade or explicit_complement or explicitly_needed:
            score = (100 if upgrade else 80 if explicit_complement else 50) + len(_tokens(name) & current_tokens) * 2
            ranked.append((score, tier, name.casefold(), item))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [item for _, _, _, item in ranked[:max(1, min(max_items, 12))]], ("eligible_filtered" if ranked else "no_eligible_products")


def source_evidence(customer: dict, signals: dict):
    """Trace source field/value pairs taken from provided rows, never LLM inventions."""
    evidence = []
    for field in ("plan_tier", "seats", "renewal_date", "industry"):
        if customer.get(field) is not None:
            evidence.append({"source": "customer_profile", "field": field, "value": str(customer[field])[:160]})
    for dataset, limit in (("usage_rows", 2), ("tickets", 2)):
        rows = signals.get(dataset) or []
        for row_index, row in enumerate(rows[-limit:] if dataset == "usage_rows" else rows[:limit]):
            if not isinstance(row, dict):
                continue
            for field, value in list(row.items())[:5]:
                if value is not None:
                    evidence.append({"source": dataset, "row_index_in_excerpt": row_index, "field": field, "value": str(value)[:160]})
    return evidence[:22]


def compact_signals(signals: dict):
    """Reduce repeated schema and raw history in agent prompts while keeping fresh signals."""
    profile = signals.get("customer_profile") or {}
    keys = ("customer_id", "customer_name", "plan_tier", "seats", "industry", "renewal_date", "account_manager")
    result = {"customer_profile": {k: profile[k] for k in keys if k in profile}}
    result["usage_rows"] = (signals.get("usage_rows") or [])[-4:]
    result["tickets"] = (signals.get("tickets") or [])[-4:]
    for k in ("dynamic_fields", "ticket_dynamic_fields", "usage_dynamic_fields", "feature_priorities"):
        v = signals.get(k)
        if v:
            result[k] = str(v)[:2000] if len(str(v)) > 2000 else v
    datasets = []
    for ds in (signals.get("datasets") or [])[:3]:
        if isinstance(ds, dict):
            datasets.append({"dataset_label": ds.get("dataset_label"), "rows": (ds.get("rows") or [])[-2:]})
    if datasets:
        result["datasets"] = datasets
    return result


def evidence_supports_expansion(signals: dict) -> bool:
    """A renewal date by itself is NOT evidence to upsell.

    Requires positive tracked usage/seat movement, high capacity pressure,
    or an explicit expansion inquiry. False negatives are safer than sales
    claims invented from a quiet account.
    """
    rows = signals.get("usage_rows") or []
    numeric_keys = ("feature_usage_score", "monthly_active_users", "monthly_orders", "active_users", "api_calls")
    for key in numeric_keys:
        values = []
        for row in rows:
            try:
                if isinstance(row, dict) and row.get(key) is not None:
                    values.append(float(row[key]))
            except (TypeError, ValueError):
                pass
        if len(values) >= 2 and values[0] > 0 and values[-1] >= values[0] * 1.10:
            return True
    if rows:
        row = rows[-1]
        if isinstance(row, dict):
            try:
                used = float(row.get("storage_used_gb") or 0)
                limit = float(row.get("storage_limit_gb") or 0)
                if limit and used / limit >= 0.85:
                    return True
            except (ValueError, TypeError, ZeroDivisionError):
                pass
    tickets = signals.get("tickets") or []
    customer_text = " ".join(str(t.get("subject") or "") + " " + str(t.get("description") or "")
                              for t in tickets if isinstance(t, dict)).lower()
    return any(phrase in customer_text for phrase in
               ("more seats", "additional seats", "expand", "upgrade", "higher-tier", "higher tier", "need more capacity"))
