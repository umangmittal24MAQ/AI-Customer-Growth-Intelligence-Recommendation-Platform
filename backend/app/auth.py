"""
Tenant authorization.

Every request that touches tenant data must present:
    X-Tenant-Id:  which company is asking
    X-API-Key:    proof that the caller is actually that company

`get_current_tenant` is a FastAPI dependency that verifies the pair and
returns the authorized tenant_id. Routes should use THIS value for every
db call -- never trust a tenant_id typed into a query param or path
directly, or any company could read/overwrite any other company's data
just by changing the URL.

Keys are stored as salted hashes (tenant_api_keys.api_key_hash), never in
plaintext, so a DB dump alone doesn't leak usable credentials.
"""

import hashlib
import os
import secrets

from fastapi import Header, HTTPException

from app import db


def _hash_key(tenant_id: str, raw_key: str) -> str:
    # tenant_id is folded into the hash input so the same raw key string
    # can't accidentally verify against a different tenant's stored hash.
    salt = os.getenv("API_KEY_SALT", "upsell-agent-static-salt")
    return hashlib.sha256(f"{salt}:{tenant_id}:{raw_key}".encode()).hexdigest()


def generate_api_key() -> str:
    """A fresh, high-entropy raw key to hand to a new tenant. Shown once --
    only the hash is ever stored."""
    return secrets.token_urlsafe(32)


def create_tenant_key(tenant_id: str, company_name: str = None) -> str:
    """Provisions (or rotates) an API key for a tenant. Returns the raw key
    -- caller is responsible for delivering it to the tenant out-of-band;
    it cannot be retrieved again after this call."""
    raw_key = generate_api_key()
    db.upsert_tenant_api_key(tenant_id, _hash_key(tenant_id, raw_key), company_name)
    return raw_key


def revoke_tenant_key(tenant_id: str) -> None:
    db.revoke_tenant_api_key(tenant_id)


def verify_tenant_key(tenant_id: str, raw_key: str) -> bool:
    record = db.get_tenant_api_key(tenant_id)
    if not record or record.get("revoked"):
        return False
    return secrets.compare_digest(record["api_key_hash"], _hash_key(tenant_id, raw_key))


def get_current_tenant(
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> str:
    """FastAPI dependency: validates the header pair and returns the
    authorized tenant_id. Any endpoint that depends on this can trust the
    returned tenant_id came from a verified caller, not an arbitrary
    client-supplied string."""
    if not verify_tenant_key(x_tenant_id, x_api_key):
        raise HTTPException(status_code=403, detail="Invalid tenant_id / API key.")
    return x_tenant_id
