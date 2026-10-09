"""
Builds prompts, calls the LLM (IndiaAI by default), and parses structured
JSON responses. Two modes:

  - get_recommendation()       : one customer per call (simple, but burns
                                  through rate/token limits fastest)
  - get_recommendations_batch(): several customers per call (used by the
                                  pipeline) -- fewer requests, less repeated
                                  system-prompt/catalog overhead.
"""

import json
from datetime import datetime
from app.indiaai_client import make_client
from app.config import (
    LLM_MODEL,
    LLM_TEMPERATURE,
)
from app.logging_config import get_logger
from app.prefilter import storage_pct_used, days_to_renewal
from app.db import get_service_usage
from app.prompts import SYSTEM_PROMPT, BATCH_SYSTEM_PROMPT

log = get_logger(__name__)

class _LazyIndiaAIClient:
    @property
    def chat(self):
        return make_client().chat

client = _LazyIndiaAIClient()


# ---------------------------------------------------------------------------
# Single-customer mode (kept for testing / small ad-hoc calls, e.g. /customer/{id})
# ---------------------------------------------------------------------------

def build_user_prompt(customer: dict, usage_rows: list[dict], tickets: list[dict], catalog: list[dict], tenant_id: str = "default") -> str:
    usage_series = [r["feature_usage_score"] for r in usage_rows]
    ticket_lines = [f"{t['category']}: {t['subject']}" for t in tickets] or ["None"]
    catalog_lines = [
        f"{p['product_id']}: {p['product_name']} (tier {p['tier_level']}, ${p['price_per_seat']}/seat)"
        for p in catalog
    ]

    # Per-service usage breakdown -- what they're actually using, not just an
    # opaque rollup number, so rationale text can name specific services.
    service_rows = get_service_usage(tenant_id, customer["customer_id"])
    if service_rows:
        latest_month = service_rows[0]["month"]
        service_lines = [
            f"{r['service_name']}: {r['usage_count']}"
            + (f" ({r['usage_pct_of_plan']}% of plan)" if r.get("usage_pct_of_plan") is not None else "")
            for r in service_rows if r["month"] == latest_month
        ]
        service_usage_text = f"Per-service usage ({latest_month}):\n" + "\n".join(service_lines)
    else:
        service_usage_text = "Per-service usage: not available"

    return f"""
Customer: {customer['customer_name']}
Current plan: {customer['plan_tier']}, {customer['seats']} seats
Industry: {customer['industry']}
Renewal date: {customer['renewal_date']} ({days_to_renewal(customer['renewal_date'])} days away)

Usage trend (last 3 months, rollup feature usage score 0-100): {usage_series}
{service_usage_text}
Storage utilization: {storage_pct_used(usage_rows)}%

Recent support tickets:
{chr(10).join(ticket_lines)}

Available products to recommend from (choose at most one, or none):
{chr(10).join(catalog_lines)}
"""


def get_recommendation(customer: dict, usage_rows: list[dict], tickets: list[dict], catalog: list[dict]) -> dict:
    user_prompt = build_user_prompt(customer, usage_rows, tickets, catalog)
    response = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    result = json.loads(response.choices[0].message.content)

    if result.get("churn_risk") == "high":
        result["recommended_product"] = None
        result["recommendation_type"] = None

    result["customer_id"] = customer["customer_id"]
    result["customer_name"] = customer["customer_name"]
    result["estimated_deal_value"] = _estimate_deal_value(result, customer, catalog)
    result["renewal_date"] = customer["renewal_date"].isoformat()
    result["generated_at"] = datetime.utcnow().isoformat()
    return result


# ---------------------------------------------------------------------------
# Batched mode (used by the pipeline) -- multiple customers per API call
# ---------------------------------------------------------------------------

def build_batch_user_prompt(items: list[tuple], catalog: list[dict], tenant_id: str = "default") -> str:
    catalog_lines = [
        f"{p['product_id']}: {p['product_name']} (tier {p['tier_level']}, ${p['price_per_seat']}/seat)"
        for p in catalog
    ]
    customer_blocks = []
    for customer, usage_rows, tickets in items:
        usage_series = [r["feature_usage_score"] for r in usage_rows]
        ticket_lines = [f"{t['category']}: {t['subject']}" for t in tickets] or ["None"]

        service_rows = get_service_usage(tenant_id, customer["customer_id"])
        if service_rows:
            latest_month = service_rows[0]["month"]
            service_bits = [
                f"{r['service_name']}={r['usage_count']}"
                + (f"({r['usage_pct_of_plan']}%)" if r.get("usage_pct_of_plan") is not None else "")
                for r in service_rows if r["month"] == latest_month
            ]
            service_usage_line = f"per-service usage ({latest_month}): {', '.join(service_bits)}"
        else:
            service_usage_line = "per-service usage: not available"

        customer_blocks.append(f"""customer_id: {customer['customer_id']}
name: {customer['customer_name']}, plan: {customer['plan_tier']}, seats: {customer['seats']}
renewal in {days_to_renewal(customer['renewal_date'])} days
usage trend (rollup score): {usage_series}
{service_usage_line}
storage used: {storage_pct_used(usage_rows)}%
tickets: {'; '.join(ticket_lines)}""")

    return f"""Product catalog:
{chr(10).join(catalog_lines)}

Customers:
{(chr(10) + '---' + chr(10)).join(customer_blocks)}
"""


def get_recommendations_batch(items: list[tuple], catalog: list[dict]) -> list[dict]:
    """items = list of (customer, usage_rows, tickets) tuples, typically 5-10 per call."""
    user_prompt = build_batch_user_prompt(items, catalog)

    response = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": BATCH_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    parsed = json.loads(response.choices[0].message.content)
    results_by_id = {r["customer_id"]: r for r in parsed.get("results", [])}
    customer_lookup = {c["customer_id"]: c for c, u, t in items}

    output = []
    for customer_id, result in results_by_id.items():
        customer = customer_lookup.get(customer_id)
        if customer is None:
            continue  # LLM returned an id we didn't send -- skip defensively

        if result.get("churn_risk") == "high":
            result["recommended_product"] = None
            result["recommendation_type"] = None

        result["customer_id"] = customer_id
        result["customer_name"] = customer["customer_name"]
        result["estimated_deal_value"] = _estimate_deal_value(result, customer, catalog)
        result["renewal_date"] = customer["renewal_date"].isoformat()
        result["generated_at"] = datetime.utcnow().isoformat()
        log.info(
            "[%s] IndiaAI LLM: product=%s churn=%s score=%s",
            customer_id, result.get("recommended_product"),
            result.get("churn_risk"), result.get("revenue_score"),
        )
        output.append(result)

    return output


def _estimate_deal_value(result: dict, customer: dict, catalog: list[dict]) -> float:
    recommended = result.get("recommended_product")
    if not recommended:
        return 0.0
    # The LLM sees catalog entries as "PROD-008: Additional Storage Pack (1TB) ...",
    # and the prompt doesn't force it to echo back the id vs. the name -- match
    # either so a deal value is still computed regardless of which one it returns.
    product = next(
        (p for p in catalog if p["product_id"] == recommended or p["product_name"] == recommended),
        None,
    )
    if not product:
        return 0.0
    return round(product["price_per_seat"] * customer["seats"] * 12, 2)
