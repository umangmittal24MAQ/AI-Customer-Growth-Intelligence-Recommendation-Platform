"""
Stage 5 of the schema-free pipeline (see schema_free_pipeline_design.md §5).

Builds the generic insight-list contract (`app.models.Insight`) for one
customer, replacing the fixed churn_analysis/bandwidth_data/etc. response
fields with a list of `{id, category, title, summary, metrics, chart_hint}`
objects.

This module previously computed insights via a fixed set of hand-written,
per-category rule-based functions (one for churn_risk, one for
revenue_opportunity, etc.), each carrying its own confidence score. That
approach has been replaced: insight generation is now a single LLM
reasoning call over this customer's actual data (see
app.insight_llm.generate_insights), so the insights that come back are
driven by what's genuinely in THIS tenant's dataset -- in plain language,
with no confidence score -- rather than a fixed template every tenant
converges on. This module is kept as a stable entry point
(`build_customer_insights`) so callers (web_api.py) don't need to change;
it does no interpretation itself anymore, just delegates.
"""

from app.insight_llm import generate_insights


def build_customer_insights(
    tenant_id: str, customer: dict, usage_rows: list[dict], tickets: list[dict],
    catalog: list[dict], latest_rec: dict | None,
) -> list[dict]:
    """Entry point: the full insight list for one customer, in plain
    language, reasoned out by the LLM from this customer's actual data.
    Returns plain dicts ready to drop into a JSON response -- see
    web_api.py's `/customers/{id}/analysis`."""
    return generate_insights(tenant_id, customer, usage_rows, tickets, catalog, latest_rec)
