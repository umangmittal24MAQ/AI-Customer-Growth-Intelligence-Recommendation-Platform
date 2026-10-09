"""
Generates schema-free demo CSVs for FOUR different industries, so a demo can
show the same agent pipeline adapting its insights to genuinely different
data shapes -- not just renamed columns on the same underlying SaaS-seat
model like generate_tenant_csvs.py's acme/globex/initech tenants.

Each tenant below has:
  - its own vocabulary (no "customer_id"/"seats"/"plan_tier" column names
    anywhere -- everything is industry-flavored)
  - a "core" entity file (something resolving to customer_id/renewal_date/
    plan_tier/seats concepts) + a "metrics" file (usage_trend_metric/
    active_users/storage_* concepts) + an "issues" file (ticket_severity/
    ticket_created_at/ticket_resolved concepts)
  - one deliberate "surprise" column with NO corresponding concept in
    schema_discovery.CONCEPTS, so it can only ever show up as a dynamic/
    custom insight (category: custom) -- proving the agent is reasoning
    over the data, not just filling in a fixed template.

Output: data/tenant_uploads/<tenant_id>/<dataset_label>.csv
Run scripts/run_tenant_ingestion.py --schema-free --tenant <tenant_id>
against each one afterward (see the printed instructions at the bottom).
"""

import csv
import os
import random
from datetime import date, timedelta

from faker import Faker

fake = Faker()
random.seed(42)

HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, "tenant_uploads")

NUM_ENTITIES = 22


def _write_csv(tenant_id: str, dataset_label: str, fieldnames: list[str], rows: list[dict]) -> str:
    tenant_dir = os.path.join(OUT_DIR, tenant_id)
    os.makedirs(tenant_dir, exist_ok=True)
    path = os.path.join(tenant_dir, f"{dataset_label}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _months_back(n):
    today = date.today()
    return [(today.replace(day=1) - timedelta(days=30 * i)).isoformat() for i in range(n, 0, -1)]


# ===========================================================================
# 1) TECH / SaaS -- techflow
#    plan-tier subscription business, closest in spirit to the seeded
#    tenants but with a totally different vocabulary + an NPS surprise col.
# ===========================================================================
def gen_techflow(tenant_id="techflow"):
    tiers = ["Starter", "Growth", "Scale"]
    accounts = []
    for i in range(NUM_ENTITIES):
        accounts.append({
            "workspace_id": f"TF-{i:04d}",
            "customer_org": fake.company(),
            "subscription_tier": random.choice(tiers),
            "licensed_seats": random.randint(15, 600),
            "renews_on": (date.today() + timedelta(days=random.randint(10, 380))).isoformat(),
            "csm_owner": fake.name(),
            "nps_last_survey": random.randint(-20, 80),  # surprise: no concept for this
        })
    _write_csv(tenant_id, "subscriptions", list(accounts[0].keys()), accounts)

    usage_rows = []
    for acc in accounts:
        base = random.randint(30, 95)
        drift = random.choice([-1, -1, 0, 1, 1, 1])  # skew slightly growing
        for idx, month in enumerate(_months_back(4)):
            score = max(5, min(100, base + drift * idx * random.randint(2, 6)))
            usage_rows.append({
                "workspace_id": acc["workspace_id"],
                "usage_month": month,
                "product_engagement_index": score,
                "monthly_active_devs": max(1, int(acc["licensed_seats"] * random.uniform(0.2, 0.9))),
                "data_stored_gb": round(random.uniform(5, 480), 1),
                "storage_plan_cap_gb": 500,
                "api_calls": random.randint(1000, 500000),
            })
    _write_csv(tenant_id, "product_usage", list(usage_rows[0].keys()), usage_rows)

    issue_types = ["billing", "security", "technical", "onboarding"]
    issues = []
    for acc in accounts:
        if random.random() < 0.55:
            opened = date.today() - timedelta(days=random.randint(1, 90))
            resolved = random.random() < 0.6
            issues.append({
                "workspace_id": acc["workspace_id"],
                "issue_category": random.choice(issue_types),
                "summary": fake.sentence(nb_words=6),
                "opened_on": opened.isoformat(),
                "is_closed": resolved,
            })
    _write_csv(tenant_id, "support_issues", list(issues[0].keys()), issues)


# ===========================================================================
# 2) MANUFACTURING -- ironforge
#    contracted industrial-equipment servicing accounts. No "seats" concept
#    at all -- "machine_count" fills the seats role instead. Surprise:
#    safety_incident_count (no concept covers this).
# ===========================================================================
def gen_ironforge(tenant_id="ironforge"):
    contract_types = ["Standard Service", "Premium Service", "Full Coverage"]
    plants = []
    for i in range(NUM_ENTITIES):
        plants.append({
            "plant_code": f"IF-{i:04d}",
            "facility_name": fake.company() + " Plant",
            "service_plan": random.choice(contract_types),
            "machine_count": random.randint(5, 220),
            "contract_expiry": (date.today() + timedelta(days=random.randint(10, 380))).isoformat(),
            "region_manager": fake.name(),
            "safety_incident_count_ytd": random.randint(0, 6),  # surprise
        })
    _write_csv(tenant_id, "service_contracts", list(plants[0].keys()), plants)

    metrics = []
    for plant in plants:
        base_uptime = random.randint(70, 98)
        drift = random.choice([-1, -1, 0, 1, 1])
        for idx, month in enumerate(_months_back(4)):
            uptime = max(40, min(100, base_uptime + drift * idx * random.randint(1, 4)))
            metrics.append({
                "plant_code": plant["plant_code"],
                "reporting_month": month,
                "equipment_uptime_pct": uptime,
                "active_machines_operating": max(1, int(plant["machine_count"] * random.uniform(0.5, 1.0))),
                "downtime_hours": round(random.uniform(0, 60), 1),
                "output_units_produced": random.randint(500, 40000),
                "maintenance_spend_usd": round(random.uniform(200, 15000), 2),
            })
    _write_csv(tenant_id, "equipment_metrics", list(metrics[0].keys()), metrics)

    req_types = ["billing", "technical", "parts_order", "safety"]
    reqs = []
    for plant in plants:
        if random.random() < 0.5:
            logged = date.today() - timedelta(days=random.randint(1, 90))
            reqs.append({
                "plant_code": plant["plant_code"],
                "request_type": random.choice(req_types),
                "description": fake.sentence(nb_words=6),
                "logged_on": logged.isoformat(),
                "closed_flag": random.random() < 0.55,
            })
    _write_csv(tenant_id, "service_requests", list(reqs[0].keys()), reqs)


# ===========================================================================
# 3) RETAIL -- brightmart
#    per-store retail chain accounts. "pos_terminals" fills the seats role.
#    Surprise: loyalty_signups_mtd.
# ===========================================================================
def gen_brightmart(tenant_id="brightmart"):
    tiers = ["Basic POS", "Advanced POS", "Enterprise Retail"]
    stores = []
    for i in range(NUM_ENTITIES):
        stores.append({
            "store_id": f"BM-{i:04d}",
            "retailer_name": fake.company(),
            "package_tier": random.choice(tiers),
            "pos_terminals": random.randint(2, 60),
            "agreement_end_date": (date.today() + timedelta(days=random.randint(10, 380))).isoformat(),
            "regional_rep": fake.name(),
            "loyalty_signups_mtd": random.randint(0, 400),  # surprise
        })
    _write_csv(tenant_id, "store_accounts", list(stores[0].keys()), stores)

    perf = []
    for store in stores:
        base = random.randint(30, 90)
        drift = random.choice([-1, -1, 0, 1, 1])
        for idx, month in enumerate(_months_back(4)):
            traffic_index = max(5, min(100, base + drift * idx * random.randint(2, 5)))
            perf.append({
                "store_id": store["store_id"],
                "sales_month": month,
                "foot_traffic_index": traffic_index,
                "active_terminals_in_use": max(1, int(store["pos_terminals"] * random.uniform(0.4, 1.0))),
                "inventory_on_hand_units": random.randint(200, 20000),
                "inventory_capacity_units": 20000,
                "avg_basket_size_usd": round(random.uniform(12, 140), 2),
            })
    _write_csv(tenant_id, "sales_performance", list(perf[0].keys()), perf)

    complaint_types = ["billing", "technical", "delivery", "returns"]
    complaints = []
    for store in stores:
        if random.random() < 0.45:
            filed = date.today() - timedelta(days=random.randint(1, 90))
            complaints.append({
                "store_id": store["store_id"],
                "complaint_type": random.choice(complaint_types),
                "notes": fake.sentence(nb_words=6),
                "filed_on": filed.isoformat(),
                "resolved": random.random() < 0.65,
            })
    _write_csv(tenant_id, "complaints", list(complaints[0].keys()), complaints)


# ===========================================================================
# 4) SALES / B2B CRM -- novasales
#    a sales-ops tooling vendor's own book of accounts. Surprise: csat_score.
# ===========================================================================
def gen_novasales(tenant_id="novasales"):
    tiers = ["Team", "Business", "Enterprise"]
    accounts = []
    for i in range(NUM_ENTITIES):
        accounts.append({
            "account_ref": f"NS-{i:04d}",
            "company_name": fake.company(),
            "plan_level": random.choice(tiers),
            "seat_licenses": random.randint(5, 300),
            "renewal_date": (date.today() + timedelta(days=random.randint(10, 380))).isoformat(),
            "ae_owner": fake.name(),
            "csat_score": round(random.uniform(2.5, 5.0), 1),  # surprise
        })
    _write_csv(tenant_id, "accounts", list(accounts[0].keys()), accounts)

    engagement = []
    for acc in accounts:
        base = random.randint(25, 90)
        drift = random.choice([-1, -1, 0, 1, 1])
        for idx, month in enumerate(_months_back(4)):
            adoption = max(5, min(100, base + drift * idx * random.randint(2, 6)))
            engagement.append({
                "account_ref": acc["account_ref"],
                "activity_month": month,
                "crm_adoption_score": adoption,
                "active_reps_logged_in": max(1, int(acc["seat_licenses"] * random.uniform(0.3, 0.95))),
                "pipeline_records_stored": random.randint(50, 8000),
                "pipeline_storage_cap": 8000,
                "emails_synced": random.randint(200, 20000),
            })
    _write_csv(tenant_id, "engagement_metrics", list(engagement[0].keys()), engagement)

    ticket_types = ["billing", "security", "integration", "training"]
    tickets = []
    for acc in accounts:
        if random.random() < 0.5:
            created = date.today() - timedelta(days=random.randint(1, 90))
            tickets.append({
                "account_ref": acc["account_ref"],
                "ticket_type": random.choice(ticket_types),
                "subject": fake.sentence(nb_words=6),
                "created_on": created.isoformat(),
                "status_closed": random.random() < 0.6,
            })
    _write_csv(tenant_id, "support_tickets", list(tickets[0].keys()), tickets)


# ===========================================================================
# Product catalogs -- one per tenant, tier-matched to that tenant's own
# plan/tier vocabulary above. Required: without a catalog, revenue_opportunity
# and upsell recommendations can't be computed at all (web_api.py correctly
# blocks "Run Full Analysis" until one exists).
# ===========================================================================
def _write_catalog(tenant_id: str, rows: list[dict]):
    _write_csv(tenant_id, "product_catalog", list(rows[0].keys()), rows)


def gen_techflow_catalog(tenant_id="techflow"):
    _write_catalog(tenant_id, [
        {"sku": "TF-STARTER", "offering_name": "Starter", "tier": 1, "seat_price_usd": 9.0, "product_group": "core-plan"},
        {"sku": "TF-GROWTH", "offering_name": "Growth", "tier": 2, "seat_price_usd": 22.0, "product_group": "core-plan"},
        {"sku": "TF-SCALE", "offering_name": "Scale", "tier": 3, "seat_price_usd": 45.0, "product_group": "core-plan"},
        {"sku": "TF-SEC", "offering_name": "Advanced Security Add-on", "tier": 2, "seat_price_usd": 6.0, "product_group": "security"},
        {"sku": "TF-ANALYTICS", "offering_name": "Analytics Dashboard Add-on", "tier": 2, "seat_price_usd": 7.5, "product_group": "analytics"},
        {"sku": "TF-STORAGE", "offering_name": "Extra Storage Pack", "tier": 1, "seat_price_usd": 3.5, "product_group": "storage"},
        {"sku": "TF-SUPPORT", "offering_name": "Priority Support Plan", "tier": 2, "seat_price_usd": 4.5, "product_group": "support"},
    ])


def gen_ironforge_catalog(tenant_id="ironforge"):
    _write_catalog(tenant_id, [
        {"sku": "IF-STD", "offering_name": "Standard Service", "tier": 1, "seat_price_usd": 15.0, "product_group": "core-plan"},
        {"sku": "IF-PREM", "offering_name": "Premium Service", "tier": 2, "seat_price_usd": 32.0, "product_group": "core-plan"},
        {"sku": "IF-FULL", "offering_name": "Full Coverage", "tier": 3, "seat_price_usd": 58.0, "product_group": "core-plan"},
        {"sku": "IF-PREDICT", "offering_name": "Predictive Maintenance Add-on", "tier": 2, "seat_price_usd": 9.0, "product_group": "technical"},
        {"sku": "IF-SAFETY", "offering_name": "Safety Compliance Add-on", "tier": 2, "seat_price_usd": 6.5, "product_group": "security"},
        {"sku": "IF-PARTS", "offering_name": "Priority Parts Program", "tier": 1, "seat_price_usd": 5.0, "product_group": "support"},
        {"sku": "IF-24-7", "offering_name": "24/7 Technician Line Add-on", "tier": 2, "seat_price_usd": 7.0, "product_group": "support"},
    ])


def gen_brightmart_catalog(tenant_id="brightmart"):
    _write_catalog(tenant_id, [
        {"sku": "BM-BASIC", "offering_name": "Basic POS", "tier": 1, "seat_price_usd": 11.0, "product_group": "core-plan"},
        {"sku": "BM-ADV", "offering_name": "Advanced POS", "tier": 2, "seat_price_usd": 26.0, "product_group": "core-plan"},
        {"sku": "BM-ENT", "offering_name": "Enterprise Retail", "tier": 3, "seat_price_usd": 49.0, "product_group": "core-plan"},
        {"sku": "BM-LOYALTY", "offering_name": "Loyalty Program Add-on", "tier": 2, "seat_price_usd": 5.5, "product_group": "analytics"},
        {"sku": "BM-INVENTORY", "offering_name": "Inventory Forecasting Add-on", "tier": 2, "seat_price_usd": 8.0, "product_group": "analytics"},
        {"sku": "BM-PAYMENTS", "offering_name": "Integrated Payments Add-on", "tier": 1, "seat_price_usd": 4.0, "product_group": "technical"},
        {"sku": "BM-SUPPORT", "offering_name": "Premium Store Support", "tier": 2, "seat_price_usd": 4.5, "product_group": "support"},
    ])


def gen_novasales_catalog(tenant_id="novasales"):
    _write_catalog(tenant_id, [
        {"sku": "NS-TEAM", "offering_name": "Team", "tier": 1, "seat_price_usd": 10.0, "product_group": "core-plan"},
        {"sku": "NS-BIZ", "offering_name": "Business", "tier": 2, "seat_price_usd": 24.0, "product_group": "core-plan"},
        {"sku": "NS-ENT", "offering_name": "Enterprise", "tier": 3, "seat_price_usd": 47.0, "product_group": "core-plan"},
        {"sku": "NS-FORECAST", "offering_name": "Pipeline Forecasting Add-on", "tier": 2, "seat_price_usd": 7.0, "product_group": "analytics"},
        {"sku": "NS-DIALER", "offering_name": "Power Dialer Add-on", "tier": 2, "seat_price_usd": 6.0, "product_group": "technical"},
        {"sku": "NS-SEC", "offering_name": "SSO & Access Controls Add-on", "tier": 2, "seat_price_usd": 5.5, "product_group": "security"},
        {"sku": "NS-CSM", "offering_name": "Dedicated CSM Plan", "tier": 3, "seat_price_usd": 9.0, "product_group": "support"},
    ])


def main():
    gen_techflow()
    gen_techflow_catalog()
    gen_ironforge()
    gen_ironforge_catalog()
    gen_brightmart()
    gen_brightmart_catalog()
    gen_novasales()
    gen_novasales_catalog()
    print("Generated demo CSVs for: techflow (tech/SaaS), ironforge (manufacturing), "
          "brightmart (retail), novasales (sales/CRM) -- including a product_catalog.csv "
          "for each, required before 'Run Full Analysis' will work.")
    print(f"Output dir: {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    main()
