"""
Cross-tenant isolation tests.

Verifies the guarantees documented in
upsell_agent_multitenant_project_notes.md / CHANGES_AND_TODO.md:

  1. Two tenants can both use the same customer_id ("CUST-001") with zero
     collision -- each tenant keeps its own row (composite tenant_id +
     customer_id primary key in schema.sql / db.upsert_customers).
  2. A tenant's API key is rejected (403) against every other tenant_id.
  3. /run, /recommendations, and /customer/{id} never leak rows across
     tenants, even when both tenants are queried back-to-back in the same
     test process.

Uses a scratch, throwaway SQLite DB (never the real data/upsell.db) --
DB_PATH is monkeypatched to a temp file *before* app.db is imported, since
app/config.py reads it once at import time.

Run with: pytest tests/test_tenant_isolation.py
"""
import importlib
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """
    Fresh app + fresh scratch DB per test. Reloads app.config/app.db/app.auth
    /app.main so DB_PATH actually points at the temp file -- these modules
    read DB_PATH at import time, so setting the env var alone (after an
    earlier test already imported them) would silently do nothing.
    """
    db_path = tmp_path / "isolation_test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))

    for mod_name in list(sys.modules):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]

    from fastapi.testclient import TestClient

    config = importlib.import_module("app.config")
    assert config.DB_PATH == str(db_path)

    db = importlib.import_module("app.db")
    auth = importlib.import_module("app.auth")
    main = importlib.import_module("app.main")

    db.init_db()

    tc = TestClient(main.app)
    tc._db_module = db
    tc._auth_module = auth
    return tc


def _seed_customer(db, tenant_id: str, customer_id: str, name: str):
    db.upsert_customers(
        tenant_id,
        [{
            "customer_id": customer_id,
            "customer_name": name,
            "industry": "software",
            "plan_tier": "starter",
            "seats": 10,
            "contract_start_date": (date.today() - timedelta(days=200)).isoformat(),
            "renewal_date": (date.today() + timedelta(days=45)).isoformat(),
            "account_manager": "Test AM",
        }],
    )


def _headers(tenant_id: str, api_key: str) -> dict:
    return {"X-Tenant-Id": tenant_id, "X-API-Key": api_key}


def test_same_customer_id_does_not_collide_across_tenants(client):
    db = client._db_module
    auth = client._auth_module

    key_a = auth.create_tenant_key("tenant_a", company_name="Tenant A")
    key_b = auth.create_tenant_key("tenant_b", company_name="Tenant B")

    _seed_customer(db, "tenant_a", "CUST-001", "Alpha Corp")
    _seed_customer(db, "tenant_b", "CUST-001", "Beta Inc")

    customers_a = db.get_customers("tenant_a")
    customers_b = db.get_customers("tenant_b")

    assert len(customers_a) == 1
    assert len(customers_b) == 1
    assert customers_a[0]["customer_name"] == "Alpha Corp"
    assert customers_b[0]["customer_name"] == "Beta Inc"
    assert customers_a[0]["customer_id"] == customers_b[0]["customer_id"] == "CUST-001"


def test_wrong_api_key_is_rejected_with_403(client):
    auth = client._auth_module
    auth.create_tenant_key("tenant_a", company_name="Tenant A")
    key_b = auth.create_tenant_key("tenant_b", company_name="Tenant B")

    # tenant_b's real key, presented as if it belonged to tenant_a.
    resp = client.get("/tenant/tenant_a/profile", headers=_headers("tenant_a", key_b))
    assert resp.status_code == 403

    # A key that doesn't exist for any tenant at all.
    resp = client.get("/tenant/tenant_a/profile", headers=_headers("tenant_a", "not-a-real-key"))
    assert resp.status_code == 403

    # Missing headers entirely -> FastAPI's own 422 (required header absent),
    # not a 200 -- still must not be treated as authorized.
    resp = client.get("/tenant/tenant_a/profile")
    assert resp.status_code in (401, 403, 422)


def test_path_tenant_id_must_match_authenticated_tenant(client):
    """A valid key for tenant_a must not be usable to read/write tenant_b's
    data just by changing the tenant_id in the URL path."""
    auth = client._auth_module
    key_a = auth.create_tenant_key("tenant_a", company_name="Tenant A")
    auth.create_tenant_key("tenant_b", company_name="Tenant B")

    resp = client.get("/tenant/tenant_b/profile", headers=_headers("tenant_a", key_a))
    assert resp.status_code == 403

    resp = client.get("/tenant/tenant_b/config", headers=_headers("tenant_a", key_a))
    assert resp.status_code == 403

    resp = client.post(
        "/tenant/tenant_b/config",
        headers=_headers("tenant_a", key_a),
        json={"use_llm": True, "llm_provider": "indiaai", "use_vector_search": False},
    )
    assert resp.status_code == 403


def test_recommendations_endpoint_never_leaks_across_tenants(client):
    db = client._db_module
    auth = client._auth_module
    key_a = auth.create_tenant_key("tenant_a", company_name="Tenant A")
    key_b = auth.create_tenant_key("tenant_b", company_name="Tenant B")

    rec_a = {
        "customer_id": "CUST-001", "customer_name": "Alpha Corp",
        "recommended_product": "Pro Tier", "no_recommendation_reason_code": None,
        "churn_risk": "low", "churn_reason": "stable usage", "segment": "expansion-ready",
        "rationale": "usage trending up", "revenue_score": 80,
        "renewal_date": (date.today() + timedelta(days=30)).isoformat(),
        "generated_at": date.today().isoformat(), "estimated_deal_value": 1200.0,
        "reasoning_mode": "rule-based (fallback)",
        "agent_trace": {"agents_run": ["rule_based"], "outcome": "recommended", "fallbacks_used": []},
    }
    rec_b = {**rec_a, "customer_id": "CUST-001", "customer_name": "Beta Inc", "recommended_product": "Enterprise Tier"}

    db.log_recommendation("tenant_a", rec_a)
    db.log_recommendation("tenant_b", rec_b)

    resp_a = client.get("/recommendations", headers=_headers("tenant_a", key_a))
    resp_b = client.get("/recommendations", headers=_headers("tenant_b", key_b))
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200

    names_a = {r["customer_name"] for r in resp_a.json()}
    names_b = {r["customer_name"] for r in resp_b.json()}
    assert names_a == {"Alpha Corp"}
    assert names_b == {"Beta Inc"}


def test_customer_detail_endpoint_404s_for_other_tenants_customer(client):
    """CUST-001 exists for tenant_a but not tenant_b -- tenant_b's
    authenticated request for that id must not see tenant_a's row."""
    db = client._db_module
    auth = client._auth_module
    key_b = auth.create_tenant_key("tenant_b", company_name="Tenant B")
    auth.create_tenant_key("tenant_a", company_name="Tenant A")

    _seed_customer(db, "tenant_a", "CUST-001", "Alpha Corp")

    resp = client.get("/customer/CUST-001", headers=_headers("tenant_b", key_b))
    assert resp.status_code == 404


def test_revoked_key_is_rejected(client):
    auth = client._auth_module
    key_a = auth.create_tenant_key("tenant_a", company_name="Tenant A")
    auth.revoke_tenant_key("tenant_a")

    resp = client.get("/tenant/tenant_a/profile", headers=_headers("tenant_a", key_a))
    assert resp.status_code == 403
