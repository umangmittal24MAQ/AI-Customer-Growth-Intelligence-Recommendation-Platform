"""
Login-time auto-onboarding.

Design: the frontend login screen now only asks for a tenant_id, no API
key. The API key still exists internally (every other route is still
protected by X-Tenant-Id + X-API-Key via app/auth.py -- nothing about that
enforcement changed), it's just no longer something a human has to see,
type, or remember. This module is the one place that:

  1. Looks up whether a tenant_id has already been provisioned. If so,
     returns its existing key (login for a returning tenant).
  2. If it's brand new: creates the API key, looks for CSVs under
     data/tenant_uploads/<tenant_id>/, ingests them if found, seeds that
     tenant's product catalog, and returns the newly-created key.

SECURITY NOTE: because there is no secret required to "become" a
tenant_id anymore, this only makes sense for a local/single-user demo
environment. Anyone who types an existing tenant_id in the login box is
now treated as that tenant -- tenant_id itself is not a proof of
identity, only a label. Do not deploy this auto-login flow anywhere more
than one person can reach without adding a real credential back in.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db
from app.auth import create_tenant_key

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "tenant_uploads")


def _tenant_has_data(tenant_id: str) -> bool:
    """Cheap check so we don't re-ingest CSVs on every subsequent login --
    only the first login for a tenant_id should trigger ingestion. Checks
    both the old fixed tables (migrated/legacy tenants) and the new
    schema-free tenant_datasets table (tenants ingested via Stage 1)."""
    return len(db.get_customers(tenant_id)) > 0 or len(db.list_tenant_datasets(tenant_id)) > 0


def _tenant_has_key(tenant_id: str) -> bool:
    record = db.get_tenant_api_key(tenant_id)
    return bool(record and not record.get("revoked"))


def _tenant_has_uploads(tenant_id: str) -> bool:
    tenant_dir = os.path.join(UPLOADS_DIR, tenant_id)
    if not os.path.isdir(tenant_dir):
        return False
    return any(f.endswith(".csv") for f in os.listdir(tenant_dir))


def bootstrap_new_tenant_data(tenant_id: str) -> tuple[dict | None, str | None]:
    """
    Runs schema-free ingestion for any CSVs already sitting under
    data/tenant_uploads/<tenant_id>/, if this tenant has no data yet.
    Returns (ingestion_summary, warning) -- both None if the tenant
    already had data (nothing to do).

    Extracted out of login_or_provision() so app/accounts.py's sign_up()
    can run the exact same bootstrap step for a brand-new self-service
    signup, instead of duplicating this logic.
    """
    if _tenant_has_data(tenant_id):
        return None, None

    if not _tenant_has_uploads(tenant_id):
        return None, (
            f"No CSVs found under data/tenant_uploads/{tenant_id}/. "
            f"Logged in with an empty account -- 0 customers."
        )

    # Import here (not at module top) to avoid circular import, since
    # run_tenant_ingestion.py itself does a sys.path insert of this same
    # backend/ directory.
    #
    # SCHEMA-FREE PIPELINE: new tenants go through
    # ingest_all_files_for_tenant_schema_free() -- Stage 1 (Schema
    # Discovery) + Stage 2 (Prompt Architect, cached) + Stage 3 (bounded
    # self-correction sample check) -- instead of the old fixed-
    # FIELD_DEFINITIONS mapping flow. See schema_free_pipeline_design.md.
    from scripts.run_tenant_ingestion import ingest_all_files_for_tenant_schema_free
    results = ingest_all_files_for_tenant_schema_free(tenant_id)
    warning = None
    if not results.get("files") or not any(r.get("status") == "ok" for r in results["files"]):
        warning = (
            f"Found file(s) for '{tenant_id}' under tenant_uploads/, "
            f"but none could be read/discovered -- see ingestion summary for details."
        )
    return results, warning


def login_or_provision(tenant_id: str) -> dict:
    """
    Called by POST /auth/login. Returns:
        {
          "tenant_id": str,
          "api_key": str,          # internal use only -- frontend stores
                                    # this in sessionStorage, never shows it
          "is_new_tenant": bool,
          "ingestion": dict | None,  # summary if auto-ingest ran, else None
          "warning": str | None,    # e.g. "no CSVs found, tenant has 0 customers"
        }
    """
    db.init_db()
    tenant_id = tenant_id.strip()
    if not tenant_id:
        raise ValueError("tenant_id must not be empty")

    is_new_tenant = not _tenant_has_key(tenant_id)

    if is_new_tenant:
        api_key = create_tenant_key(tenant_id, company_name=tenant_id)
    else:
        # Returning tenant: we can't recover the raw key (only its hash is
        # stored), so re-issue one. This mirrors "log in and we hand you a
        # fresh session" rather than "here is your original password."
        api_key = create_tenant_key(tenant_id, company_name=tenant_id)

    ingestion_summary, warning = bootstrap_new_tenant_data(tenant_id)

    # NOTE: this used to auto-seed a shared demo product catalog here for any
    # tenant with zero catalog rows. Removed intentionally -- it silently
    # masked "this tenant never uploaded a catalog" (see app/web_api.py's
    # can_run_analysis / _data_gaps, which now hard-block analysis instead).
    # A tenant with no catalog now simply has none, and must upload
    # data/tenant_uploads/<tenant_id>/product_catalog.csv (then run
    # scripts/run_tenant_ingestion.py, or POST it through the ingestion
    # endpoint) before analysis can run for them.

    return {
        "tenant_id": tenant_id,
        "api_key": api_key,
        "is_new_tenant": is_new_tenant,
        "ingestion": ingestion_summary,
        "warning": warning,
    }
