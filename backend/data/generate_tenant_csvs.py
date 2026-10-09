"""
Generates synthetic MESSY tenant CSVs — one folder per tenant, one CSV per
dataset type — deliberately using non-internal column names, missing optional
columns, and a couple of tenant-specific "surprise" columns.

This is different from generate_synthetic_data.py, which writes clean rows
(already using our internal column names) straight into the DB and never
touches schema_mapping.py at all. This script exists to actually exercise the
onboarding pipeline end to end:

    raw tenant file -> onboard_tenant() [fuzzy + LLM mapping]
                     -> save_column_mapping() [confirm]
                     -> ingest_file() [apply mapping, validate, upsert]
                     -> discover_unmapped_columns() [classify leftovers]

Output: data/tenant_uploads/<tenant_id>/<dataset_type>.csv

Each tenant is deliberately designed to hit a different part of the mapping
logic:

  - acme        customers columns are close to our KNOWN_ALIASES -> should
                resolve via fuzzy matching alone, no LLM needed. Adds one
                surprise column ("NPS") not in our schema at all.
  - globex      customers columns are abbreviated/reordered enough that fuzzy
                matching alone won't confidently resolve all of them -> needs
                the LLM step. Adds a different surprise column
                ("Contract_Type": annual/monthly).
  - initech     customers + usage_metrics + support_tickets, with their own
                renamed columns (Client_ID ties all three files together)
                and their own surprise column ("Priority_Score" on
                support_tickets).

Run this before scripts/run_tenant_ingestion.py. Doesn't touch upsell.db.
"""

import csv
import os
import random
from datetime import date, timedelta

from faker import Faker

fake = Faker()
random.seed(7)

HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, "tenant_uploads")

NUM_ROWS = 25


def _write_csv(tenant_id: str, dataset_type: str, fieldnames: list[str], rows: list[dict]) -> str:
    tenant_dir = os.path.join(OUT_DIR, tenant_id)
    os.makedirs(tenant_dir, exist_ok=True)
    path = os.path.join(tenant_dir, f"{dataset_type}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# acme -- customers, fuzzy-resolvable column names + surprise "NPS" column
# ---------------------------------------------------------------------------
def gen_acme_customers():
    fieldnames = ["Cust_ID", "Company", "Plan", "NumSeats", "ContractEnd", "NPS"]
    rows = []
    for i in range(NUM_ROWS):
        rows.append({
            "Cust_ID": f"ACME-{i:04d}",
            "Company": fake.company(),
            "Plan": random.choice(["Business Standard", "E1", "E3"]),
            "NumSeats": random.randint(20, 800),
            "ContractEnd": (date.today() + timedelta(days=random.randint(15, 400))).isoformat(),
            "NPS": random.randint(0, 10),
        })
    return _write_csv("acme", "customers", fieldnames, rows)


# ---------------------------------------------------------------------------
# globex -- customers, abbreviated names that need the LLM mapping step +
# surprise "Contract_Type" column
# ---------------------------------------------------------------------------
def gen_globex_customers():
    fieldnames = ["Acct", "Org", "Tier", "Lic_Cnt", "Rnwl_Dt", "Contract_Type"]
    rows = []
    for i in range(NUM_ROWS):
        rows.append({
            "Acct": f"GLBX-{i:04d}",
            "Org": fake.company(),
            "Tier": random.choice(["Business Standard", "E1", "E3"]),
            "Lic_Cnt": random.randint(20, 800),
            "Rnwl_Dt": (date.today() + timedelta(days=random.randint(15, 400))).isoformat(),
            "Contract_Type": random.choice(["annual", "monthly"]),
        })
    return _write_csv("globex", "customers", fieldnames, rows)


# ---------------------------------------------------------------------------
# initech -- customers, usage_metrics + support_tickets, renamed columns +
# surprise "Priority_Score" column on support_tickets.
#
# customers.csv uses "Client_ID" (same key as usage_metrics/support_tickets
# below) so all three files resolve to the same INIT-xxxx customer_id after
# mapping -- without this file, usage/ticket rows would ingest against
# customer_ids that never exist in the customers table (SQLite doesn't
# enforce the FK by default, so that failure mode is silent), and this
# tenant could never produce a recommendation.
# ---------------------------------------------------------------------------
def gen_initech_customers():
    fieldnames = ["Client_ID", "Org_Name", "Plan_Tier", "Seat_Count", "Renewal", "Sector"]
    rows = []
    for i in range(NUM_ROWS):
        rows.append({
            "Client_ID": f"INIT-{i:04d}",
            "Org_Name": fake.company(),
            "Plan_Tier": random.choice(["Business Standard", "E1", "E3"]),
            "Seat_Count": random.randint(20, 800),
            "Renewal": (date.today() + timedelta(days=random.randint(15, 400))).isoformat(),
            "Sector": random.choice(
                ["Manufacturing", "Retail", "Healthcare", "Finance", "Technology"]
            ),
        })
    return _write_csv("initech", "customers", fieldnames, rows)


# ---------------------------------------------------------------------------
# initech -- usage_metrics + support_tickets, renamed columns + surprise
# "Priority_Score" column on support_tickets
# ---------------------------------------------------------------------------
def gen_initech_usage_metrics():
    # feature_usage_score is REQUIRED by data_ingestion.py even though
    # app/usage_rollup.py can derive it from per-service usage -- a raw
    # tenant file uploaded through this path still needs to supply it (or a
    # loader would need to compute the rollup before calling ingest_file()).
    # Included here so this demo file can actually ingest end to end.
    # Engagement_Trend is a deliberate "surprise" column outside the fixed
    # schema, added to test the usage-level dynamic-field path (previously
    # only support_tickets had a surprise column here).
    fieldnames = ["Client_ID", "Period", "MAU", "GB_Used", "GB_Limit", "Usage_Score", "Engagement_Trend"]
    rows = []
    for i in range(NUM_ROWS):
        month = (date.today().replace(day=1) - timedelta(days=30)).isoformat()
        rows.append({
            "Client_ID": f"INIT-{i:04d}",
            "Period": month,
            "MAU": random.randint(20, 500),
            "GB_Used": round(random.uniform(50, 900), 1),
            "GB_Limit": 1000,
            "Usage_Score": round(random.uniform(10, 95), 1),
            "Engagement_Trend": random.choice(["declining", "flat", "rising"]),
        })
    return _write_csv("initech", "usage_metrics", fieldnames, rows)


def gen_initech_support_tickets():
    fieldnames = ["Case_ID", "Client_ID", "Opened_At", "Issue_Type", "Title", "Closed", "Priority_Score"]
    rows = []
    for i in range(NUM_ROWS):
        rows.append({
            "Case_ID": f"TCK-{i:05d}",
            "Client_ID": f"INIT-{random.randint(0, NUM_ROWS - 1):04d}",
            "Opened_At": (date.today() - timedelta(days=random.randint(1, 120))).isoformat(),
            "Issue_Type": random.choice(["billing", "technical", "security"]),
            "Title": fake.sentence(nb_words=6),
            "Closed": random.choice([True, False]),
            "Priority_Score": random.randint(1, 5),
        })
    return _write_csv("initech", "support_tickets", fieldnames, rows)


def main():
    paths = [
        gen_acme_customers(),
        gen_globex_customers(),
        gen_initech_customers(),
        gen_initech_usage_metrics(),
        gen_initech_support_tickets(),
    ]
    print(f"Generated {len(paths)} messy tenant CSV(s) under {OUT_DIR}:")
    for p in paths:
        print(f"  - {os.path.relpath(p, HERE)}")


if __name__ == "__main__":
    main()
