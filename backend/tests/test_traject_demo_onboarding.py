"""Regression checks for the user-facing Traject demo onboarding paths.

These tests deliberately use disposable directories and do not require IndiaAI.
"""

from pathlib import Path
import json
from types import SimpleNamespace

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


def test_schema_discovery_accepts_unfamiliar_column_names(monkeypatch):
    frame = pd.DataFrame([
        {'orbital_key': 'A-1', 'friendly_caption': 'Acme', 'next_checkpoint': '2027-01-01',
         'capacity_units': 20},
        {'orbital_key': 'A-2', 'friendly_caption': 'Beta', 'next_checkpoint': '2027-02-01',
         'capacity_units': 40},
    ])
    result = {
        'dataset_label': 'account roster',
        'join_key_column': 'orbital_key',
        'columns': [
            {'column': 'orbital_key', 'inferred_label': 'Account key', 'description': 'Unique account',
             'dtype': 'identifier', 'semantic_role': 'entity_id', 'relevance': 'high', 'concept': 'customer_id'},
            {'column': 'friendly_caption', 'inferred_label': 'Account name', 'description': 'Display name',
             'dtype': 'categorical', 'semantic_role': 'dimension', 'relevance': 'high', 'concept': 'customer_name'},
            {'column': 'next_checkpoint', 'inferred_label': 'Renewal', 'description': 'Next renewal date',
             'dtype': 'date', 'semantic_role': 'metric', 'relevance': 'high', 'concept': 'renewal_date'},
            {'column': 'capacity_units', 'inferred_label': 'Licensed capacity', 'description': 'Purchased units',
             'dtype': 'numeric', 'semantic_role': 'metric', 'relevance': 'high', 'concept': 'seats'},
        ],
    }
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))])
    completions = SimpleNamespace(create=lambda **kwargs: response)
    monkeypatch.setattr(schema_discovery, '_client', lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=completions)))
    discovered = schema_discovery.discover_schema(frame, 'mystery.csv')
    assert discovered['join_key_column'] == 'orbital_key'
    assert {c['column']: c['concept'] for c in discovered['columns']} == {
        'orbital_key': 'customer_id', 'friendly_caption': 'customer_name',
        'next_checkpoint': 'renewal_date', 'capacity_units': 'seats'}
