"""
Calibration Plugin — runs ONCE at tenant onboarding, and periodically after
(e.g. monthly, or once enough outcome feedback exists).

This is NOT model training. It's statistical calibration: computing this
tenant's own usage/deal-size distribution so pre-filter thresholds and LLM
prompts are relative to THEIR data, not a hardcoded global assumption.

Why this exists: a marketplace product has many tenants, each with wildly
different scale and usage patterns. A hardcoded "usage trend >= 10%" or
"storage >= 80%" threshold might be meaningless for a tenant whose customers
never cross 40% storage, or trivially always-true for one whose customers
run hot by default. Calibration makes "notable" relative to each tenant.
"""

import statistics
from datetime import datetime, date
from app import db
from app.logging_config import get_logger
from app.config import (
    USAGE_TREND_THRESHOLD_PCT,
    STORAGE_UTILIZATION_THRESHOLD_PCT,
    RENEWAL_WINDOW_DAYS,
)
from app.prefilter import compute_usage_trend, storage_pct_used

log = get_logger(__name__)

MIN_SAMPLE_SIZE_FOR_CALIBRATION = 20  # below this, fall back to global defaults
MIN_OUTCOMES_FOR_FEEDBACK_RECALIBRATION = 20


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def compute_tenant_profile(tenant_id: str = "default") -> dict:
    """
    Computes a calibration profile from this tenant's own customer data.
    Falls back to global defaults if there isn't enough data yet (cold start
    within a tenant that just onboarded with very few customers).
    """
    customers = db.get_customers(tenant_id)
    catalog = db.get_product_catalog(tenant_id)

    usage_scores = []
    usage_trends = []
    storage_pcts = []

    for customer in customers:
        usage_rows = db.get_usage(tenant_id, customer["customer_id"])
        if not usage_rows:
            continue
        usage_scores.append(usage_rows[-1]["feature_usage_score"])
        usage_trends.append(compute_usage_trend(usage_rows))
        storage_pct = storage_pct_used(usage_rows)
        if storage_pct is not None:
            storage_pcts.append(storage_pct)

    sample_size = len(usage_scores)

    if sample_size < MIN_SAMPLE_SIZE_FOR_CALIBRATION:
        # Not enough data yet -- use global defaults, mark as low-confidence
        profile = {
            "tenant_id": tenant_id,
            "usage_baseline_p50": 50.0,
            "usage_baseline_p90": 80.0,
            "usage_growth_p75": USAGE_TREND_THRESHOLD_PCT,
            "storage_threshold_pct": STORAGE_UTILIZATION_THRESHOLD_PCT,
            "avg_deal_size": _estimate_avg_deal_size(customers, catalog),
            "renewal_window_days": RENEWAL_WINDOW_DAYS,
            "total_customers": len(customers),
            "sample_size": sample_size,
            "min_score_threshold": 40.0,
            "calibrated_at": datetime.utcnow().isoformat(),
            "calibration_source": "initial_onboarding_fallback_defaults",
        }
    else:
        profile = {
            "tenant_id": tenant_id,
            "usage_baseline_p50": round(_percentile(usage_scores, 50), 1),
            "usage_baseline_p90": round(_percentile(usage_scores, 90), 1),
            "usage_growth_p75": round(_percentile(usage_trends, 75), 1),
            "storage_threshold_pct": (
                round(_percentile(storage_pcts, 75), 1) if storage_pcts else STORAGE_UTILIZATION_THRESHOLD_PCT
            ),
            "avg_deal_size": _estimate_avg_deal_size(customers, catalog),
            "renewal_window_days": RENEWAL_WINDOW_DAYS,
            "total_customers": len(customers),
            "sample_size": sample_size,
            "min_score_threshold": 40.0,
            "calibrated_at": datetime.utcnow().isoformat(),
            "calibration_source": "initial_onboarding",
        }

    db.save_tenant_profile(profile)
    return profile


def _estimate_avg_deal_size(customers: list[dict], catalog: list[dict]) -> float:
    if not customers or not catalog:
        return 0.0
    avg_price = statistics.mean(p["price_per_seat"] for p in catalog)
    avg_seats = statistics.mean(c["seats"] for c in customers)
    return round(avg_price * avg_seats * 12, 2)  # annualized


def recalibrate_from_feedback(tenant_id: str = "default") -> dict | None:
    """
    Periodic recalibration using logged outcomes (accepted/rejected/converted).
    Only runs once enough feedback exists -- otherwise there's nothing
    statistically meaningful to adjust yet. This is the closest thing to
    "learning" in this architecture, and it's still just statistics, not
    a trained model.
    """
    outcomes = db.get_recommendations_with_outcomes(tenant_id)
    if len(outcomes) < MIN_OUTCOMES_FOR_FEEDBACK_RECALIBRATION:
        log.info(
            "Only %d outcomes logged, need %d to recalibrate. Skipping.",
            len(outcomes), MIN_OUTCOMES_FOR_FEEDBACK_RECALIBRATION,
        )
        return None

    converted_scores = [o["revenue_score"] for o in outcomes if o["outcome"] == "converted"]
    rejected_scores = [o["revenue_score"] for o in outcomes if o["outcome"] == "rejected"]

    if not converted_scores:
        log.info("No converted outcomes yet -- skipping threshold recalibration.")
        return None

    # Set the score threshold just below the lowest score that has actually
    # converted, so future runs favor recommendations similar to past wins.
    new_threshold = max(0, min(converted_scores) - 5)

    profile = db.get_tenant_profile(tenant_id) or {}
    profile["min_score_threshold"] = round(new_threshold, 1)
    profile["calibrated_at"] = datetime.utcnow().isoformat()
    profile["calibration_source"] = "feedback_recalibration"
    profile["tenant_id"] = tenant_id

    db.save_tenant_profile(profile)
    log.info(
        "Recalibrated min_score_threshold to %s based on %d conversions, %d rejections.",
        new_threshold, len(converted_scores), len(rejected_scores),
    )
    return profile


if __name__ == "__main__":
    profile = compute_tenant_profile()
    print("Tenant profile computed:")
    for k, v in profile.items():
        print(f"  {k}: {v}")
