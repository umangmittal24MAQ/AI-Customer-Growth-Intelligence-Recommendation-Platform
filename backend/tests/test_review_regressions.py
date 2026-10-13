"""Review regressions, using disposable storage and no live services."""
import importlib
from pathlib import Path
import pytest


@pytest.fixture
def storage(tmp_path, monkeypatch):
    db = importlib.import_module('app.db')
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'review.db'))
    db.init_db()
    return db


def test_chat_ownership(storage, monkeypatch):
    chat = importlib.import_module('app.chat_agent')
    monkeypatch.setattr(chat, 'db', storage)
    monkeypatch.setattr(chat, '_sessions', {})
    cid, first = chat._get_or_create_session(None, 'a')
    chat._add_to_history(first, 'user', 'private')
    other_id, other = chat._get_or_create_session(cid, 'b')
    assert other_id != cid and other['history'] == []
    assert not chat.clear_session(cid, 'b')
    assert chat.get_session_history(cid, 'a') == first['history']
    storage.save_chat_session({**first, 'tenant_id': 'b', 'history': []})
    assert storage.load_chat_session(cid, 'a')['history'] == first['history']
    chat._sessions.clear()
    assert chat._get_or_create_session(cid, 'a')[1]['history'] == first['history']


def test_same_schema_refreshes_records(storage, tmp_path, monkeypatch):
    module = importlib.import_module('app.schema_discovery')
    monkeypatch.setattr(module, 'db', storage)
    monkeypatch.setattr(module, '_client', lambda: None)
    path = tmp_path / 'subscriptions.csv'
    path.write_text('workspace_id,licensed_seats\nA,10\n')
    first = module.ingest_file('a', str(path), path.name)
    monkeypatch.setattr(module, 'discover_schema', lambda *args: pytest.fail('schema should be cached'))
    path.write_text('workspace_id,licensed_seats\nA,20\nB,30\n')
    module.ingest_file('a', str(path), path.name)
    assert storage.get_dataset_rows('a', first['dataset_id']) == [
        {'workspace_id': 'A', 'licensed_seats': 20},
        {'workspace_id': 'B', 'licensed_seats': 30}]
    assert storage.get_tenant_dataset('a', path.name)['row_count'] == 2


def test_catalog_ids_and_ownership(storage):
    product = storage.add_catalog_product('a', 'Plan', 'core', 1, 10)
    pid = product['product_id']
    assert isinstance(pid, str) and pid
    assert storage.tenant_dataset_counts('a')['product_catalog'] == 1
    assert storage.update_catalog_product('b', pid, {'product_name': 'Wrong'}) is None
    assert storage.update_catalog_product('a', pid, {'product_name': 'New'})['product_name'] == 'New'
    assert not storage.remove_catalog_product('b', pid)
    assert storage.remove_catalog_product('a', pid)


def test_login_retries_existing_tenant(storage, tmp_path, monkeypatch):
    onboarding = importlib.import_module('app.onboarding')
    ingestion = importlib.import_module('scripts.run_tenant_ingestion')
    monkeypatch.setattr(onboarding, 'db', storage)
    monkeypatch.setattr(onboarding, 'UPLOADS_DIR', str(tmp_path))
    storage.upsert_tenant_dataset('a', 'customers', 'old.csv', 1, 'id', 'v1')
    folder = tmp_path / 'a'
    folder.mkdir()
    (folder / 'new.csv').write_text('id\nA\n')
    calls = []
    def ingest(tenant):
        calls.append(tenant)
        return {'files': [{'status': 'ok'}]}
    monkeypatch.setattr(ingestion, 'ingest_all_files_for_tenant_schema_free', ingest)
    onboarding.bootstrap_new_tenant_data('a')
    assert calls == ['a']


@pytest.mark.parametrize('model,expected', [('recurring', 2400), ('one_time', 200)])
def test_revenue_model(model, expected):
    from app.agents.deal_value_agent import compute_deal_value
    result = compute_deal_value({'recommended_product': 'Plan'}, {'seats': 10},
        [{'product_name': 'Plan', 'price_per_seat': 20}], model)
    assert result.estimated_value == expected


def test_upgrade_deal_value_is_incremental():
    from app.agents.deal_value_agent import compute_deal_value
    catalog = [
        {'product_name': 'Base', 'category': 'core', 'price_per_seat': 10},
        {'product_name': 'Plus', 'category': 'core', 'price_per_seat': 25},
        {'product_name': 'Addon', 'category': 'addon', 'price_per_seat': 5},
    ]
    customer = {'seats': 10, 'plan_tier': 'Base'}
    assert compute_deal_value({'recommended_product': 'Plus'}, customer, catalog).estimated_value == 1800
    assert compute_deal_value({'recommended_product': 'Addon'}, customer, catalog).estimated_value == 600


def test_recommendation_numeric_contract_is_enforced():
    from app.models import RecommendationDraft
    draft = RecommendationDraft(
        segment='growth', churn_risk='low', churn_reason='stable', rationale='evidence',
        revenue_score=360, confidence=4,
    )
    assert draft.revenue_score == 100
    assert draft.confidence == 1


def test_schema_concepts_are_scoped_and_choose_one_primary_trend():
    from app.schema_discovery import _sanitize_concepts
    columns = [
        {'column': 'period_key', 'inferred_label': 'Reporting date', 'description': '', 'concept': 'usage_date'},
        {'column': 'installed_units', 'inferred_label': 'Active terminals', 'description': 'Terminals actively in use', 'concept': 'seats'},
        {'column': 'basket_value', 'inferred_label': 'Average basket size', 'description': 'Transaction value', 'concept': 'price_per_seat'},
        {'column': 'visitation_gauge', 'inferred_label': 'Foot traffic index', 'description': 'Store traffic index', 'concept': 'active_users'},
        {'column': 'raw_visits', 'inferred_label': 'Visit count', 'description': 'Number of visits', 'concept': 'usage_trend_metric'},
    ]
    result = _sanitize_concepts(columns)
    concepts = {entry['column']: entry['concept'] for entry in result}
    assert concepts['installed_units'] == 'active_users'
    assert concepts['basket_value'] is None
    assert concepts['visitation_gauge'] == 'usage_trend_metric'
    assert concepts['raw_visits'] is None


def test_schema_free_adapters_use_concepts_not_headers(storage):
    def add_dataset(label, filename, join_key, columns, rows):
        dataset_id = storage.upsert_tenant_dataset('free', label, filename, len(rows), join_key, filename)
        storage.replace_tenant_schema_columns('free', dataset_id, [
            {'column': name, 'dtype': dtype, 'semantic_role': 'metric',
             'relevance': 'high', 'concept': concept}
            for name, dtype, concept in columns])
        storage.replace_tenant_records('free', dataset_id, [
            {'entity_id': str(row[join_key]) if join_key else None, 'row': row} for row in rows])

    add_dataset('entities', 'a', 'x1', [
        ('x1', 'identifier', 'customer_id'), ('x2', 'categorical', 'customer_name'),
        ('x3', 'date', 'renewal_date'), ('x4', 'numeric', 'seats'), ('x5', 'categorical', 'plan_tier')],
        [{'x1': 'C-1', 'x2': 'Concept Corp', 'x3': '2027-01-01', 'x4': 12, 'x5': 'Base'}])
    add_dataset('events', 'b', 'u1', [
        ('u1', 'identifier', 'customer_id'), ('u2', 'date', 'usage_date'),
        ('u3', 'numeric', 'usage_trend_metric'), ('api_calls', 'numeric', 'usage_trend_metric')],
        [{'u1': 'C-1', 'u2': '2026-01-01', 'u3': 20, 'api_calls': 100},
         {'u1': 'C-1', 'u2': '2026-02-01', 'u3': 40, 'api_calls': 1000}])
    add_dataset('cases', 'c', 't1', [
        ('t1', 'identifier', 'customer_id'), ('t2', 'categorical', 'ticket_category'),
        ('t3', 'free_text', 'ticket_subject'), ('t4', 'date', 'ticket_created_at'),
        ('t5', 'boolean', 'ticket_resolved')],
        [{'t1': 'C-1', 't2': 'technical', 't3': 'API latency', 't4': '2026-01-15', 't5': False}])
    add_dataset('offers', 'd', None, [
        ('p1', 'identifier', 'product_id'), ('p2', 'categorical', 'product_name'),
        ('p3', 'numeric', 'price_per_seat'), ('p4', 'numeric', 'product_tier_level'),
        ('p5', 'categorical', 'product_category'), ('p6', 'free_text', 'product_description')],
        [{'p1': 'P-1', 'p2': 'Base', 'p3': 10, 'p4': 1, 'p5': 'core', 'p6': 'Entry product'}])

    customer = storage.get_customers('free')[0]
    usage = storage.get_usage('free', 'C-1')
    ticket = storage.get_tickets('free', 'C-1')[0]
    product = storage.get_product_catalog('free')[0]
    assert customer['customer_name'] == 'Concept Corp' and customer['seats'] == 12
    assert [row['feature_usage_score'] for row in usage] == [20, 40]
    assert ticket['category'] == 'technical' and ticket['subject'] == 'API latency'
    assert product['product_name'] == 'Base' and product['category'] == 'core'
    assert product['description'] == 'Entry product'


@pytest.mark.parametrize('domain', ['amazon', 'techflow', 'ironforge', 'brightmart', 'novasales'])
def test_signup_presets_generate_files(tmp_path, monkeypatch, domain):
    accounts = importlib.import_module('app.accounts')
    monkeypatch.setattr(accounts, 'UPLOADS_DIR', str(tmp_path))
    if domain == 'amazon':
        # Signup imports this generator through its data-directory path.
        monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'data'))
        generator = importlib.import_module('generate_amazon_demo')
    else:
        generator = importlib.import_module('data.generate_industry_demo_csvs')
    monkeypatch.setattr(generator, 'OUT_DIR', str(tmp_path))
    accounts._seed_domain_dataset('preset-test', domain)
    files = list((tmp_path / 'preset-test').glob('*.csv'))
    assert len(files) == 4
    assert (tmp_path / 'preset-test' / 'product_catalog.csv').exists()
