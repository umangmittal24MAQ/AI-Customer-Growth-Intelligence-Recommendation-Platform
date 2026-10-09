"""
Unit tests for the rule-based pre-filter, using hand-crafted customers
that mirror the three main archetypes. Run with: pytest tests/test_prefilter.py
"""

import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.prefilter import passes_prefilter, compute_usage_trend, storage_pct_used


def make_usage_rows(scores, storage_pcts, limit=1000):
    rows = []
    for i, (score, pct) in enumerate(zip(scores, storage_pcts)):
        rows.append({
            "feature_usage_score": score,
            "storage_used_gb": pct / 100 * limit,
            "storage_limit_gb": limit,
        })
    return rows


def test_expansion_ready_customer_passes():
    customer = {"renewal_date": date.today() + timedelta(days=45)}
    usage_rows = make_usage_rows([50, 58, 68], [50, 65, 88])
    tickets = [{"category": "security", "subject": "...", "created_at": date.today() - timedelta(days=20)}]
    assert passes_prefilter(customer, usage_rows, tickets) is True


def test_stable_customer_does_not_pass():
    customer = {"renewal_date": date.today() + timedelta(days=200)}
    usage_rows = make_usage_rows([50, 51, 49], [40, 41, 39])
    tickets = []
    assert passes_prefilter(customer, usage_rows, tickets) is False


def test_customer_near_renewal_passes_even_without_other_signals():
    customer = {"renewal_date": date.today() + timedelta(days=30)}
    usage_rows = make_usage_rows([50, 50, 50], [40, 40, 40])
    tickets = []
    assert passes_prefilter(customer, usage_rows, tickets) is True


def test_usage_trend_calculation():
    rows = make_usage_rows([50, 60, 75], [0, 0, 0])
    assert compute_usage_trend(rows) == 50.0  # (75-50)/50 * 100


def test_storage_pct_calculation():
    rows = make_usage_rows([0, 0], [0, 91])
    assert storage_pct_used(rows) == 91.0


if __name__ == "__main__":
    test_expansion_ready_customer_passes()
    test_stable_customer_does_not_pass()
    test_customer_near_renewal_passes_even_without_other_signals()
    test_usage_trend_calculation()
    test_storage_pct_calculation()
    print("All prefilter tests passed.")
