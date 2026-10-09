"""
Cheap, deterministic pre-filter. No LLM call happens here — this is what
keeps LLM cost/latency bounded as the customer base grows. Only customers
that pass this filter get sent to the LLM.
"""

from datetime import date, datetime, timedelta
from app.config import (
    USAGE_TREND_THRESHOLD_PCT,
    STORAGE_UTILIZATION_THRESHOLD_PCT,
    TICKET_LOOKBACK_DAYS,
    RENEWAL_WINDOW_DAYS,
)


def _as_date(value):
    """Coerce date | datetime | ISO-8601 string -> date.

    passes_prefilter runs two ways: directly on DB rows (real date objects)
    and as an agent tool, where the model round-trips the arguments as JSON
    so dates arrive as ISO strings. Accept both so date math never blows up.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"Cannot interpret {value!r} as a date")


def compute_usage_trend(usage_rows: list[dict]) -> float:
    """% change in feature_usage_score from first to last tracked month."""
    if len(usage_rows) < 2:
        return 0.0
    first = usage_rows[0]["feature_usage_score"]
    last = usage_rows[-1]["feature_usage_score"]
    if first == 0:
        return 0.0
    return round(((last - first) / first) * 100, 1)


def storage_pct_used(usage_rows: list[dict]) -> float | None:
    """Returns None (not 0.0) when this tenant has no storage concept at
    all (storage_limit_gb is None -- see db.py's normalizer), so callers
    can tell "not applicable to this business" apart from "genuinely at
    0% of quota" instead of silently treating the former as the latter."""
    if not usage_rows:
        return None
    latest = usage_rows[-1]
    limit = latest.get("storage_limit_gb")
    used = latest.get("storage_used_gb")
    if limit is None or used is None or limit == 0:
        return None
    return round((used / limit) * 100, 1)


def has_relevant_ticket(tickets: list[dict], days: int = TICKET_LOOKBACK_DAYS) -> bool:
    cutoff = date.today() - timedelta(days=days)
    return any(
        t["category"] in ("security", "technical") and _as_date(t["created_at"]) >= cutoff
        for t in tickets
    )


def days_to_renewal(renewal_date) -> int:
    return (_as_date(renewal_date) - date.today()).days


def passes_prefilter(customer: dict, usage_rows: list[dict], tickets: list[dict], tenant_profile: dict = None) -> bool:
    """
    Shortlist a customer for LLM reasoning if ANY of these hold:
      - usage trend >= threshold (default +10%, or this tenant's calibrated p75 growth)
      - storage utilization >= threshold (default 80%, or this tenant's calibrated value)
      - a security/technical ticket within the lookback window
      - renewal is within the defined window (default 90 days)

    tenant_profile, if provided (from app.calibration), overrides the global
    defaults with values computed from this tenant's own data distribution --
    this is what makes "notable usage growth" relative to each marketplace
    customer instead of a hardcoded one-size-fits-all number.
    """
    trend_threshold = (
        tenant_profile["usage_growth_p75"] if tenant_profile else USAGE_TREND_THRESHOLD_PCT
    )
    storage_threshold = (
        tenant_profile["storage_threshold_pct"] if tenant_profile else STORAGE_UTILIZATION_THRESHOLD_PCT
    )

    trend = compute_usage_trend(usage_rows)
    storage = storage_pct_used(usage_rows)
    ticket_flag = has_relevant_ticket(tickets)
    renewal_days = days_to_renewal(customer["renewal_date"])

    # Shortlist only accounts with actionable signals. Non-shortlisted accounts
    # can still receive deterministic low-confidence context downstream.
    return (
        trend >= trend_threshold
        or (storage is not None and storage >= storage_threshold)
        or ticket_flag
        or (0 <= renewal_days <= RENEWAL_WINDOW_DAYS)
    )


def estimate_churn_risk(customer: dict, usage_rows: list[dict], tickets: list[dict]) -> tuple[str, str]:
    """Deterministic churn-risk estimate shared by every code path that can
    produce a recommendation (rule engine AND the no-LLM-call "low
    confidence pitch" path in agents/pitch.py). Previously the pitch path
    hardcoded churn_risk="low" for every customer the prefilter didn't
    shortlist -- which is exactly the customers with a *declining* usage
    trend (the prefilter's trend check only shortlists on growth, not
    decline), so a genuinely at-risk account with no open ticket and a
    distant renewal was silently mislabeled "low" and could never show up
    in a "High Churn Risk" count. Centralizing the rule here means both
    paths agree.

    The reason text is built from this customer's actual numbers (trend %,
    days to renewal, which billing ticket is open) rather than a fixed
    sentence -- a flat rule-based template read identically across every
    high-risk customer, which is misleading even though the underlying
    risk classification itself was already per-customer.
    """
    trend = compute_usage_trend(usage_rows)
    renewal_days = days_to_renewal(customer["renewal_date"])
    open_billing_tickets = [
        t for t in tickets if t.get("category") == "billing" and not t.get("resolved")
    ]
    billing_open = bool(open_billing_tickets)

    if trend <= -15 or (renewal_days <= 60 and billing_open):
        parts = []
        if trend <= -15:
            parts.append(f"usage is down {abs(trend):.0f}% over the tracked period")
        if renewal_days <= 60 and billing_open:
            subject = open_billing_tickets[0].get("subject") or open_billing_tickets[0].get("issue")
            billing_detail = f"open billing ticket ({subject})" if subject else "an unresolved billing ticket"
            parts.append(f"renewal is only {renewal_days} days out with {billing_detail}")
        elif renewal_days <= 60:
            parts.append(f"renewal is only {renewal_days} days out")
        reason = "; ".join(parts).capitalize() + "."
        return "high", reason
    elif trend < 0:
        return "medium", f"Usage trend is slightly negative ({trend:.0f}% over the tracked period)."
    else:
        return "low", f"Usage trend is stable or growing ({trend:+.0f}%), no unresolved concerns."


def get_prefilter_signals(customer: dict, usage_rows: list[dict], tickets: list[dict]) -> dict:
    """Returns the computed signals — useful for debugging/logging why a customer was shortlisted."""
    return {
        "usage_trend_pct": compute_usage_trend(usage_rows),
        "storage_pct_used": storage_pct_used(usage_rows),
        "has_relevant_ticket": has_relevant_ticket(tickets),
        "days_to_renewal": days_to_renewal(customer["renewal_date"]),
    }
