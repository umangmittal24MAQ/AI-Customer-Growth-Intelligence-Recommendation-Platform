"""
Self-service tenant signup/login by email + password.

This is the real credential layer app/onboarding.py's tenant-id-only login
was explicitly NOT (see the security note there) -- a tenant now proves
who they are with a password they set themselves, not just by typing a
label. Design:

  tenant_accounts (email, password_hash, client_name) is the identity a
  human logs in with. tenant_api_keys (the existing X-Tenant-Id/X-API-Key
  mechanism every route is already protected by, see app/auth.py) is
  UNCHANGED underneath -- login here just verifies the password, then
  reissues a fresh api_key the same way app/onboarding.py's
  login_or_provision() always did, so nothing else in the request-auth
  path needed to change.

  tenant_id itself is derived from the client_name the tenant chooses at
  signup (slugified), disambiguated with a numeric suffix on collision --
  it is a label for their data (matches data/tenant_uploads/<tenant_id>/,
  same as before), not a login credential anymore.

  Signup creates that data/tenant_uploads/<tenant_id>/ folder immediately
  (empty) and does NOT run ingestion -- there's nothing to ingest yet.
  The intended flow is: sign up -> redirected to log in -> upload data
  files into that folder (outside the app, e.g. via file system/SFTP/etc.)
  -> log in -> schema-free ingestion (Stage 1-3) runs automatically against
  whatever's now in the folder. Every login re-checks and ingests if the
  tenant has files but no data yet, so "upload files, then log in" is all
  that's needed to connect them -- no separate upload step in the app.

Passwords are hashed with salted PBKDF2-HMAC-SHA256 (200k iterations, a
random 16-byte salt per account) -- NOT the same static-salt SHA256 used
for API keys in app/auth.py. API keys are the caller's own long random
secret (a static salt is fine there, see that module's own note); a
human-chosen password needs a slow, per-user-salted hash so that a stolen
password_hash column can't be cracked cheaply or in bulk via rainbow
tables. No new dependency (bcrypt/passlib) was added for this --
hashlib.pbkdf2_hmac is stdlib and adequate for a project at this scale;
swap to bcrypt/argon2 if this ever needs to scale past a demo/internal
tool.
"""

import hashlib
import os
import re
import secrets
import threading

from app import db
from app.auth import create_tenant_key
from app.onboarding import bootstrap_new_tenant_data, UPLOADS_DIR

PBKDF2_ITERATIONS = 200_000
MIN_PASSWORD_LENGTH = 8
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return secrets.compare_digest(candidate, digest)


def _slugify_tenant_id(client_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", client_name.strip().lower()).strip("-")
    return slug or "tenant"


def _unique_tenant_id(client_name: str) -> str:
    """First free tenant_id derived from client_name -- appends -2, -3, ...
    on collision so two tenants can share a display name (e.g. two
    different "Acme" signups) without silently overwriting each other's
    data/tenant_uploads/<tenant_id>/ folder."""
    base = _slugify_tenant_id(client_name)
    tenant_id = base
    suffix = 2
    while db.get_tenant_api_key(tenant_id) or db.get_account_by_tenant_id(tenant_id):
        tenant_id = f"{base}-{suffix}"
        suffix += 1
    return tenant_id



_DOMAIN_GENERATORS = {}

def _seed_domain_dataset(tenant_id: str, domain: str | None) -> None:
    """If a domain preset was chosen at signup, auto-generate that industry's
    demo CSVs into data/tenant_uploads/<tenant_id>/ so the tenant has real
    data to analyse on their very first login (bootstrap_new_tenant_data
    runs on login and picks up whatever is in that folder)."""
    if not domain:
        return
    try:
        if domain == "amazon":
            import sys
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(backend_dir, "data")
            if data_dir not in sys.path:
                sys.path.insert(0, data_dir)
            from generate_amazon_demo import generate_amazon_dataset
            generate_amazon_dataset(tenant_id)
        elif domain == "techflow":
            from data.generate_industry_demo_csvs import gen_techflow, gen_techflow_catalog
            gen_techflow(tenant_id)
            gen_techflow_catalog(tenant_id)
        elif domain == "ironforge":
            from data.generate_industry_demo_csvs import gen_ironforge, gen_ironforge_catalog
            gen_ironforge(tenant_id)
            gen_ironforge_catalog(tenant_id)
        elif domain == "brightmart":
            from data.generate_industry_demo_csvs import gen_brightmart, gen_brightmart_catalog
            gen_brightmart(tenant_id)
            gen_brightmart_catalog(tenant_id)
        elif domain == "novasales":
            from data.generate_industry_demo_csvs import gen_novasales, gen_novasales_catalog
            gen_novasales(tenant_id)
            gen_novasales_catalog(tenant_id)
        elif domain == "traject-showcase":
            # Curated synthetic evidence-based demo; no public/customer PII.
            from scripts.generate_trust_demo import make_dataset
            from pathlib import Path
            make_dataset(12, Path(UPLOADS_DIR) / tenant_id)
            (Path(UPLOADS_DIR) / tenant_id / "reviewer_labels_DO_NOT_UPLOAD.csv").unlink(missing_ok=True)
    except Exception as exc:
        # Non-fatal — the tenant still gets an empty account and can upload
        # files manually, just as before.
        import logging
        logging.getLogger(__name__).warning(
            "Domain dataset seed failed for tenant %s (domain=%s): %s",
            tenant_id, domain, exc,
        )


def sign_up(client_name: str, email: str, password: str, confirm_password: str, domain: str | None = None) -> dict:
    """
    Creates a new tenant account. Raises ValueError with a user-facing
    message on any validation failure -- callers (app/main.py's
    POST /auth/signup) turn that straight into a 400.

    Returns the same shape login_or_provision()/log_in() do:
        {tenant_id, api_key, client_name, email, is_new_tenant, ingestion, warning}
    so the frontend can treat signup and login identically once either
    succeeds (store api_key, proceed into the app).
    """
    client_name = (client_name or "").strip()
    email_norm = (email or "").strip().lower()

    if not client_name:
        raise ValueError("Client name is required.")
    if not email_norm or not _EMAIL_RE.match(email_norm):
        raise ValueError("Enter a valid email address.")
    if not password:
        raise ValueError("Password is required.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if password != confirm_password:
        raise ValueError("Passwords do not match.")
    if db.get_account_by_email(email_norm):
        raise ValueError("An account with this email already exists. Try logging in instead.")

    db.init_db()
    tenant_id = _unique_tenant_id(client_name)
    api_key = create_tenant_key(tenant_id, company_name=client_name)
    db.create_tenant_account(tenant_id, client_name, email_norm, _hash_password(password))

    # Create the tenant's upload folder immediately.
    os.makedirs(os.path.join(UPLOADS_DIR, tenant_id), exist_ok=True)

    # If a domain preset was selected, auto-seed the matching demo dataset
    # so the tenant has data to analyse immediately after their first login.
    _seed_domain_dataset(tenant_id, domain)

    return {
        "tenant_id": tenant_id,
        "api_key": api_key,
        "client_name": client_name,
        "email": email_norm,
        "is_new_tenant": True,
        "ingestion": None,
        "warning": (
            f"Demo data is ready for first sign-in." if domain else
            f"Account created. Put CSV files in data/tenant_uploads/{tenant_id}/ and sign in to connect them."
        ),
    }


def log_in(email: str, password: str) -> dict:
    """
    Verifies email + password and reissues a fresh api_key for that
    tenant. Raises ValueError (-> 401) on any failure -- deliberately the
    SAME message for "no such email" and "wrong password" so a login
    attempt can't be used to enumerate which emails are registered.
    """
    email_norm = (email or "").strip().lower()
    generic_error = "Incorrect email or password."

    if not email_norm or not password:
        raise ValueError(generic_error)
        
    if db.count_recent_failed_logins(email_norm) >= 5:
        raise ValueError("Too many failed login attempts. Please try again later.")

    account = db.get_account_by_email(email_norm)
    if not account or not _verify_password(password, account["password_hash"]):
        db.record_login_attempt(email_norm, False)
        raise ValueError(generic_error)
        
    db.record_login_attempt(email_norm, True)

    tenant_id = account["tenant_id"]
    key_record = db.get_tenant_api_key(tenant_id)
    if not key_record or key_record.get("revoked"):
        raise ValueError("This account's access has been revoked. Contact support.")

    # Reissue a fresh session key on every login -- mirrors
    # login_or_provision()'s existing behavior (see app/onboarding.py):
    # we never stored the raw key (only its hash), so there is nothing
    # to "recover" -- a new one each login is the session token.
    api_key = create_tenant_key(tenant_id, company_name=account["client_name"])

    # Run schema-free ingestion now in the background, in case files were dropped
    # into data/tenant_uploads/<tenant_id>/ since signup.
    # We do this in a thread so login returns instantly and we don't block
    # the web server's worker pool for minutes.
    threading.Thread(target=bootstrap_new_tenant_data, args=(tenant_id,), daemon=True).start()

    return {
        "tenant_id": tenant_id,
        "api_key": api_key,
        "client_name": account["client_name"],
        "email": account["email"],
        "is_new_tenant": False,
        "ingestion": {"status": "started_in_background"},
        "warning": None,
    }
