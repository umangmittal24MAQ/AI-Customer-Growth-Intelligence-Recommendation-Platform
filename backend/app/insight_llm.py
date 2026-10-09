"""
LLM-reasoned customer insights.

Replaces the previous rule-based approach (a fixed set of hand-written
functions -- one for churn_risk, one for revenue_opportunity, one per
"known" dynamic category) with a single reasoning call: the model is handed
everything actually known about this customer -- their record, usage
history, support tickets, product catalog, latest recommendation, and any
tenant-specific ("surprise") columns discovered at ingestion -- and asked to
say, in plain English, what actually matters. Nothing is templated ahead of
time; if the data doesn't support a claim, the model leaves it out rather
than emitting a hedge or a placeholder.

No confidence score is produced or shown -- that number was for us to judge
data quality, not for a reader deciding whether to trust the sentence. If
the model isn't sure something is worth saying, the fix is to not say it,
not to say it quietly.

Falls back to a minimal, deterministic set of insights (also confidence-free,
also in plain language) if the IndiaAI call is unavailable or fails --
see _fallback_insights below. This mirrors the pattern used elsewhere in the
pipeline (prompt_architect.py's _fallback_prompt_spec, clients.py's
build_signal_fallback): a live model call with a conservative, structurally
identical local fallback, never a hard failure the caller has to handle.
"""

import json

from app.indiaai_client import optional_client

from app.config import (
    LLM_MODEL,
)
from app import db
from app.agents.payload import is_schema_free_tenant
from app.dynamic_context import build_dynamic_field_context
from app.logging_config import get_logger
from app.models import Insight, InsightMetric
from app.prefilter import compute_usage_trend, days_to_renewal

log = get_logger(__name__)


def _client() -> object | None:
    return optional_client()


def _gather_dynamic_fields(tenant_id: str, customer: dict) -> list[dict]:
    """Tenant-specific columns with real values for this customer --
    registered dynamic fields (NPS, CSAT, etc.) plus genuinely "surprise"
    columns Stage 1 found no concept mapping for at all. This is what lets
    the model's output actually differ per tenant/industry instead of every
    tenant converging on the same handful of insights."""
    out = list(build_dynamic_field_context(tenant_id, customer, dataset_type="customers"))
    if is_schema_free_tenant(tenant_id):
        for f in db.get_unmapped_customer_fields(tenant_id, customer["customer_id"], limit=5):
            out.append({
                "field_name": f["field_name"],
                "description": f["description"] or f["label"],
                "value": f["value"],
            })
    return out


def _build_data_payload(
    tenant_id: str, customer: dict, usage_rows: list[dict], tickets: list[dict],
    catalog: list[dict], latest_rec: dict | None,
) -> dict:
    """Everything real (no interpretation, no pre-computed verdicts beyond
    a couple of cheap derived numbers) that's known about this one customer.
    Handed to the model as-is -- it does the reasoning, not us."""
    payload = {
        "customer": {k: v for k, v in customer.items() if v is not None},
        "usage_history": usage_rows[-12:],  # recent window is plenty of context
        "support_tickets": tickets[-20:],
        "product_catalog": [
            {k: v for k, v in p.items() if k in ("product_name", "product_id", "price", "tier")}
            for p in (catalog or [])
        ],
        "dynamic_fields": _gather_dynamic_fields(tenant_id, customer),
    }
    if usage_rows:
        payload["computed"] = {
            "usage_trend_pct": compute_usage_trend(usage_rows),
        }
    if customer.get("renewal_date"):
        payload.setdefault("computed", {})["days_to_renewal"] = days_to_renewal(customer["renewal_date"])
    if latest_rec:
        payload["latest_recommendation"] = {
            k: v for k, v in latest_rec.items()
            if k in (
                "recommended_product", "estimated_deal_value", "churn_risk",
                "churn_reason", "rationale", "segment",
            ) and v is not None
        }
    return payload


PROMPT = """You are a business analyst preparing a briefing for a non-technical account manager \
who has never seen this raw data and doesn't know or care what columns, models, or scores produced \
it. You will be given everything known about one customer. Read it and decide what's actually worth \
telling this person.

Rules:
- Base every statement ONLY on data present in the payload. Never invent a number, trend, or fact \
that isn't there.
- Write for a total non-technical reader: plain sentences, no jargon, no column names, no mention of \
data sources, models, or "confidence". State things plainly, e.g. "Usage has dropped 22% over the \
last three months" not "usage_trend_metric indicates a decline".
- Do not produce a confidence score or hedge language ("likely", "may indicate", "it's possible \
that") -- either the data supports a clear statement or you leave it out entirely.
- Only include an insight if the data actually supports it. If there's nothing meaningful to say \
about a topic (e.g. no ticket history), skip that topic rather than saying "no data available".
- Surface genuinely customer-specific things too -- an unusual dynamic field, a notable ticket \
pattern, a contract detail -- not just a generic template every customer would get.
- Produce between 2 and 6 insights. Fewer, better insights beat padding.
- For each insight give a short plain-language title (3-6 words, e.g. "Renewal Coming Up Soon", not \
"Contract Health"), a one-or-two sentence plain-English summary, a short free-text category label of \
your choosing (e.g. "risk", "revenue", "usage", "billing", "support", or something more specific to \
this data), and, only where genuinely useful, a small list of metrics as {{"label", "value", "unit"}} \
tuples (plain labels a reader would recognize, e.g. "Renewal in" / 18 / "days" -- not raw column \
names).

Customer data:
{data}

Return ONLY a JSON object of the form:
{{"insights": [{{"title": ..., "category": ..., "summary": ..., "metrics": [{{"label": ..., \
"value": ..., "unit": ...}}, ...], "chart_hint": "bar"|"line"|"gauge"|null}}, ...]}}
No preamble, no markdown fences."""


def _fallback_insights(customer: dict, usage_rows: list[dict], latest_rec: dict | None) -> list[Insight]:
    """Minimal, deterministic, still confidence-free and plain-language --
    used only if the LLM call is unavailable or fails. Intentionally small:
    a short, honest list beats a long rule-based one pretending to be the
    real reasoning pass."""
    out: list[Insight] = []
    if latest_rec and latest_rec.get("churn_risk"):
        risk = latest_rec["churn_risk"].lower()
        reason = latest_rec.get("churn_reason") or f"This customer's risk of leaving is currently assessed as {risk}."
        out.append(Insight(
            id=f"risk:{customer['customer_id']}", category="risk",
            title="Renewal Risk", summary=reason, metrics=[], chart_hint="gauge",
        ))
    if usage_rows:
        trend = compute_usage_trend(usage_rows)
        direction = "up" if trend > 0 else ("down" if trend < 0 else "flat")
        out.append(Insight(
            id=f"usage:{customer['customer_id']}", category="usage",
            title="Usage Trend",
            summary=f"Product usage is {direction} {abs(trend):.0f}% recently.",
            metrics=[InsightMetric(label="Usage trend", value=trend, unit="%")],
            chart_hint="line",
        ))
    if latest_rec and latest_rec.get("estimated_deal_value"):
        value = round(latest_rec["estimated_deal_value"], 2)
        out.append(Insight(
            id=f"revenue:{customer['customer_id']}", category="revenue",
            title="Upsell Opportunity",
            summary=(
                f"There's an estimated ${value:,.0f}/year opportunity here"
                + (f" via {latest_rec['recommended_product']}." if latest_rec.get("recommended_product") else ".")
            ),
            metrics=[InsightMetric(label="Estimated value", value=value, unit="USD/yr")],
            chart_hint="bar",
        ))
    if customer.get("renewal_date"):
        days = days_to_renewal(customer["renewal_date"])
        out.append(Insight(
            id=f"renewal:{customer['customer_id']}", category="contract",
            title="Renewal Timing",
            summary=f"Renewal is {days} days away.",
            metrics=[InsightMetric(label="Days to renewal", value=days)],
        ))
    if not out:
        out.append(Insight(
            id=f"no_data:{customer['customer_id']}", category="custom",
            title="Not Enough Data Yet",
            summary="There isn't enough data on this customer yet to generate meaningful insights.",
            metrics=[],
        ))
    return out


def _parse_insights(raw: dict, customer_id: str) -> list[Insight]:
    items = raw.get("insights")
    if not isinstance(items, list):
        raise ValueError("LLM response missing an 'insights' list")
    out = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("title") or not item.get("summary"):
            continue
        metrics = []
        for m in item.get("metrics") or []:
            if isinstance(m, dict) and m.get("label") is not None and m.get("value") is not None:
                metrics.append(InsightMetric(label=str(m["label"]), value=m["value"], unit=m.get("unit")))
        out.append(Insight(
            id=f"{item.get('category', 'custom')}:{i}:{customer_id}",
            category=str(item.get("category") or "custom"),
            title=str(item["title"]),
            summary=str(item["summary"]),
            metrics=metrics,
            chart_hint=item.get("chart_hint"),
        ))
    if not out:
        raise ValueError("LLM returned no usable insights")
    return out


def generate_insights(
    tenant_id: str, customer: dict, usage_rows: list[dict], tickets: list[dict],
    catalog: list[dict], latest_rec: dict | None,
) -> list[dict]:
    """Entry point: the full, plain-language insight list for one customer.
    Returns plain dicts (model_dump()) ready to drop into a JSON response --
    see web_api.py's `/customers/{id}/analysis`."""
    client = _client()
    if client is None:
        log.warning("No IndiaAI key -- using fallback insights for customer '%s'.", customer["customer_id"])
        return [i.model_dump() for i in _fallback_insights(customer, usage_rows, latest_rec)]

    payload = _build_data_payload(tenant_id, customer, usage_rows, tickets, catalog, latest_rec)
    prompt = PROMPT.format(data=json.dumps(payload, indent=2, default=str))

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = json.loads(resp.choices[0].message.content)
        insights = _parse_insights(raw, customer["customer_id"])
        return [i.model_dump() for i in insights]
    except Exception as e:
        log.warning(
            "Insight generation LLM call failed for customer '%s' (%s) -- using fallback.",
            customer["customer_id"], e,
        )
        return [i.model_dump() for i in _fallback_insights(customer, usage_rows, latest_rec)]
