"""
Provision, rotate, revoke, and list tenant API keys.

Every company (tenant) using this agent needs a tenant_id + API key pair
before any of its data can be read or written -- see app/auth.py. This
script is the operator-side counterpart: a human (you) runs this once per
new company to hand them their credentials.

Usage:
    python scripts/manage_tenants.py create acme --name "Acme Corp"
    python scripts/manage_tenants.py create synthetic_clean --name "Globex (demo)"
    python scripts/manage_tenants.py list
    python scripts/manage_tenants.py revoke acme
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db
from app.auth import create_tenant_key, revoke_tenant_key


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Provision (or rotate) an API key for a tenant.")
    p_create.add_argument("tenant_id")
    p_create.add_argument("--name", default=None, help="Human-readable company name.")

    p_revoke = sub.add_parser("revoke", help="Revoke a tenant's API key immediately.")
    p_revoke.add_argument("tenant_id")

    sub.add_parser("list", help="List every provisioned tenant.")

    args = parser.parse_args()
    db.init_db()  # safe/idempotent

    if args.command == "create":
        raw_key = create_tenant_key(args.tenant_id, company_name=args.name)
        print(f"Tenant '{args.tenant_id}' provisioned.")
        print(f"  X-Tenant-Id: {args.tenant_id}")
        print(f"  X-API-Key:   {raw_key}")
        print("\nThis key is shown ONCE -- store it now. It is not recoverable; "
              "re-run 'create' for this tenant_id to rotate it if lost.")
    elif args.command == "revoke":
        revoke_tenant_key(args.tenant_id)
        print(f"Tenant '{args.tenant_id}' API key revoked. Every request for this "
              f"tenant will now get 403 until a new key is created.")
    elif args.command == "list":
        tenants = db.list_tenants()
        if not tenants:
            print("No tenants provisioned yet.")
            return
        for t in tenants:
            status = "REVOKED" if t["revoked"] else "active"
            print(f"  {t['tenant_id']:<24} {t.get('company_name') or '':<24} {status:<8} since {t['created_at']}")


if __name__ == "__main__":
    main()
