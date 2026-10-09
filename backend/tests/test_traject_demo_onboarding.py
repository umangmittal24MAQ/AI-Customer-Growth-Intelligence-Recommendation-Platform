"""Regression checks for the user-facing Traject demo onboarding paths.

These tests deliberately use disposable directories and do not require IndiaAI.
"""

from pathlib import Path

import pandas as pd

from app import schema_discovery
from data import generate_industry_demo_csvs as demos


def test_local_schema_fallback_maps_known_demo_concepts(monkeypatch):
    monkeypatch.setattr(schema_discovery, '_client', lambda: None)
    frame = pd.DataFrame([{
        'workspace_id': 'TF-1',
        'customer_org': 'Sample Inc',
        'licensed_seats': 20,
        'renews_on': '2027-01-01',
        'nps_last_survey': 65,
    }])
    schema = schema_discovery.discover_schema(frame, 'subscriptions')
    fields = {item['column']: item['concept'] for item in schema['columns']}
    assert schema['join_key_column'] == 'workspace_id'
    assert fields['workspace_id'] == 'customer_id'
    assert fields['customer_org'] == 'customer_name'
    assert fields['licensed_seats'] == 'seats'
    assert fields['renews_on'] == 'renewal_date'
    assert fields['nps_last_survey'] is None  # never invent semantics for surprises


def test_industry_demo_is_tenant_scoped_and_has_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(demos, 'OUT_DIR', str(tmp_path))
    tenant_id = 'my-custom-traject-demo'
    demos.gen_techflow(tenant_id)
    demos.gen_techflow_catalog(tenant_id)
    tenant_dir = tmp_path / tenant_id
    assert {p.name for p in tenant_dir.glob('*.csv')} == {
        'subscriptions.csv', 'product_usage.csv', 'support_issues.csv', 'product_catalog.csv'
    }
    assert not (tmp_path / 'techflow').exists()
    assert len(pd.read_csv(tenant_dir / 'subscriptions.csv')) == demos.NUM_ENTITIES
    assert len(pd.read_csv(tenant_dir / 'product_catalog.csv')) > 0
