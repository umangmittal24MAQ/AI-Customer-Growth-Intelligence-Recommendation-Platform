"""
Turns the per-service usage breakdown (app/db.py's service_usage table)
into the single feature_usage_score that existing scoring math in
pipeline.py / prefilter.py already expects -- so nothing downstream needs
to change, but the number is now explainable: every score can point back
to exactly which services drove it (see app/citation.py).
"""

from app.db import get_service_usage

# Simple, transparent weighting -- equal by default. If some services matter
# more for upsell signal than others, adjust weights here (single place).
DEFAULT_WEIGHT = 1.0
SERVICE_WEIGHTS = {
    # "api_access": 1.5,
    # "sso": 0.5,
}


def compute_feature_usage_score(tenant_id: str, customer_id: str, month: str = None) -> dict:
    """
    Returns:
        {
            "score": float in [0, 1],
            "based_on": [{"service_name", "usage_pct_of_plan", "weight"}, ...]
        }
    Falls back to score=0.0, based_on=[] if there's no service_usage data
    for this customer/month (e.g. legacy data ingested before this feature).
    """
    rows = get_service_usage(tenant_id, customer_id, month=month)
    if not rows:
        return {"score": 0.0, "based_on": []}

    weighted_sum = 0.0
    weight_total = 0.0
    based_on = []
    for row in rows:
        pct = row.get("usage_pct_of_plan")
        if pct is None:
            continue
        weight = SERVICE_WEIGHTS.get(row["service_name"], DEFAULT_WEIGHT)
        weighted_sum += pct * weight
        weight_total += weight
        based_on.append({
            "service_name": row["service_name"],
            "usage_pct_of_plan": pct,
            "weight": weight,
        })

    score = round(weighted_sum / weight_total, 4) if weight_total else 0.0
    return {"score": score, "based_on": based_on}
