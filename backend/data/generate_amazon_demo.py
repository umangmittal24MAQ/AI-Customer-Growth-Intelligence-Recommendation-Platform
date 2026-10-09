"""
Amazon E-Commerce / FBA Demo Dataset Generator.
Generates CSVs for an Amazon Marketplace Seller management platform.
Run: python data/generate_amazon_demo.py
Or called programmatically: generate_amazon_dataset(tenant_id)
"""

import csv
import os
import random
from datetime import date, timedelta

try:
    from faker import Faker
    fake = Faker()
    HAS_FAKER = True
except ImportError:
    HAS_FAKER = False

random.seed(123)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "tenant_uploads")
NUM_ENTITIES = 22

STORE_NAMES = [
    "Galaxy Electronics", "TechVault Store", "QuickShip Goods", "MegaDeal Hub",
    "Urban Style Seller", "HomeEssentials Plus", "PrimePick Store", "SportZone Direct",
    "EcoLife Products", "BudgetBuy Central", "LuxuryFinds Official", "KidZone Toys",
    "PetPal Supplies", "AutoParts World", "FoodFresh Organics", "BeautyBox Seller",
    "FitGear Pro", "NestCraft Home", "TravelReady Gear", "GardenBloom Store",
    "OfficeElite Supplies", "BookHaven Direct",
]

ISSUE_TYPES = [
    "Listing Hijack", "FBA Reimbursement", "Account Suspension",
    "A+ Content Error", "Policy Violation",
]

ISSUE_DESCS = [
    "Account flagged for review by Amazon compliance team.",
    "FBA reimbursement pending for damaged inventory.",
    "Listing removed due to IP complaint.",
    "A+ content rejected by Amazon moderation.",
    "Seller account at risk of suspension.",
    "Seller rating dropped below threshold.",
    "Storage limit exceeded, excess units being removed.",
]


def _write_csv(tenant_id, label, fieldnames, rows):
    d = os.path.join(OUT_DIR, tenant_id)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, label + ".csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return p


def _months_back(n):
    today = date.today()
    return [
        (today.replace(day=1) - timedelta(days=30 * i)).isoformat()
        for i in range(n, 0, -1)
    ]


def generate_amazon_dataset(tenant_id="amazon"):
    """
    Generates four CSVs under data/tenant_uploads/<tenant_id>/:
      - amazon_sellers.csv  (entity/customer file)
        NOTE: 'seats' column = number of active marketplace storefronts/channels
              so the pipeline can compute a meaningful deal value.
      - seller_metrics.csv  (monthly usage/performance metrics)
      - support_tickets.csv (issues/support data)
      - product_catalog.csv (Amazon seller upsell services)
    """
    tiers = ["Individual", "Professional", "Enterprise"]

    # 1. Sellers (entity file)
    # 'seats' = number of marketplace channels / storefronts active
    # This lets the deal-value formula (price_per_seat * seats * 12) work correctly.
    sellers = []
    for i in range(NUM_ENTITIES):
        name = STORE_NAMES[i] if i < len(STORE_NAMES) else f"Seller Store {i:04d}"
        tier = random.choice(tiers)
        # Seats = marketplace channels: Individual=1, Professional=2-5, Enterprise=5-15
        seats = {"Individual": random.randint(1, 2),
                 "Professional": random.randint(2, 5),
                 "Enterprise": random.randint(5, 15)}[tier]
        sellers.append({
            "seller_id": f"AMZ-{i:04d}",
            "store_name": name,
            "subscription_tier": tier,
            "seats": seats,                         # marketplace channels = seats for deal-value calc
            "active_asins": random.randint(50, 5000),
            "seller_rating": round(random.uniform(3.2, 5.0), 1),
            "account_health": random.choice(["Good", "Good", "Good", "At Risk", "Critical"]),
            "renewal_date": (date.today() + timedelta(days=random.randint(30, 365))).isoformat(),
        })
    p1 = _write_csv(tenant_id, "amazon_sellers", list(sellers[0].keys()), sellers)
    print("  Sellers:", p1)

    # 2. Monthly FBA and Ads metrics (usage file)
    metrics = []
    for s in sellers:
        base = random.randint(15000, 250000)
        # Realistic distribution: some growing, most flat/declining
        drift = random.choice([-0.12, -0.08, -0.05, -0.03, 0, 0, 0.04, 0.08, 0.12])
        for idx, month in enumerate(_months_back(6)):
            sales = max(2000, int(base * (1 + drift * idx)))
            storage_used = round(random.uniform(100, 1800), 1)
            metrics.append({
                "seller_id": s["seller_id"],
                "reporting_month": month,
                "monthly_gmv_usd": sales,
                "fba_storage_used_cbf": storage_used,
                "fba_storage_limit_cbf": 2000,
                "fba_storage_utilization_pct": round(storage_used / 2000 * 100, 1),
                "sponsored_ads_spend_usd": round(sales * random.uniform(0.05, 0.22), 2),
                "ads_acos_pct": round(random.uniform(15, 45), 1),      # Advertising Cost of Sale %
                "return_rate_pct": round(random.uniform(1.5, 18.0), 1),
                "order_defect_rate_pct": round(random.uniform(0.1, 3.5), 2),
            })
    p2 = _write_csv(tenant_id, "seller_metrics", list(metrics[0].keys()), metrics)
    print("  Metrics:", p2)

    # 3. Support Tickets (issues file)
    tickets = []
    for s in sellers:
        if random.random() < 0.65:
            opened = date.today() - timedelta(days=random.randint(1, 90))
            severity = random.choice(["low", "medium", "medium", "high"])
            tickets.append({
                "seller_id": s["seller_id"],
                "issue_type": random.choice(ISSUE_TYPES),
                "severity": severity,
                "description": random.choice(ISSUE_DESCS),
                "opened_date": opened.isoformat(),
                "resolved": random.random() < 0.65,
            })
    if tickets:
        p3 = _write_csv(tenant_id, "support_tickets", list(tickets[0].keys()), tickets)
        print("  Tickets:", p3)

    # 4. Product Catalog — Amazon seller upsell services
    # price_per_seat × marketplace_channels × 12 = annual deal value
    catalog = [
        # Core Advertising Services
        {"product_id": "AMZ-ADS-STARTER", "product_name": "Sponsored Ads Starter",          "category": "Advertising",  "description": "Entry-level PPC management for new sellers. Keyword research, campaign setup, weekly optimization.",   "price_per_seat": 199.0},
        {"product_id": "AMZ-ADS-PRO",     "product_name": "Sponsored Ads Pro Management",   "category": "Advertising",  "description": "Full-service PPC management. DSP ads, retargeting, brand campaigns, A/B testing, ACoS optimization.", "price_per_seat": 499.0},
        {"product_id": "AMZ-ADS-ENT",     "product_name": "Advertising Enterprise Suite",   "category": "Advertising",  "description": "End-to-end advertising strategy including DSP, video ads, AMC analytics, and dedicated ad manager.",   "price_per_seat": 999.0},

        # FBA & Logistics
        {"product_id": "AMZ-FBA-OPT",    "product_name": "FBA Inventory Optimization",      "category": "Logistics",    "description": "Demand forecasting, reorder alerts, stranded inventory recovery, and IPI score improvement.",         "price_per_seat": 299.0},
        {"product_id": "AMZ-FBA-MULTI",  "product_name": "Multi-Channel Fulfillment Pro",   "category": "Logistics",    "description": "Extend FBA to Shopify, eBay, and Walmart. Unified inventory and automated routing.",                  "price_per_seat": 449.0},

        # Content & Branding
        {"product_id": "AMZ-APLUS",      "product_name": "A+ Content Creation",             "category": "Branding",     "description": "Premium A+ modules, comparison charts, brand story pages. Proven to increase conversion 5-10%.",    "price_per_seat": 899.0},
        {"product_id": "AMZ-BRAND",      "product_name": "Brand Registry Pro",              "category": "Branding",     "description": "Brand Registry setup, counterfeit protection, enhanced brand content, and storefront design.",       "price_per_seat": 299.0},
        {"product_id": "AMZ-VIDEO",      "product_name": "Sponsored Brand Video Package",   "category": "Branding",     "description": "Professional product video production and Sponsored Brand Video ad launch for top ASINs.",           "price_per_seat": 599.0},

        # SEO & Listings
        {"product_id": "AMZ-SEO",        "product_name": "Listing Optimization Pro",        "category": "SEO",          "description": "Title, bullets, description, backend keywords optimized for A9 algorithm. Monthly refresh included.", "price_per_seat": 349.0},
        {"product_id": "AMZ-REVIEW",     "product_name": "Review Velocity Program",         "category": "SEO",          "description": "Vine enrollment, Request-a-Review automation, and review monitoring dashboard.",                    "price_per_seat": 199.0},

        # Growth & Strategy
        {"product_id": "AMZ-GLOBAL",     "product_name": "Global Marketplace Expansion",   "category": "Strategy",     "description": "Launch to EU, UK, JP, CA markets. Translation, compliance, currency, and FBA setup per region.",   "price_per_seat": 1499.0},
        {"product_id": "AMZ-ANALYTICS",  "product_name": "Seller Analytics Dashboard",     "category": "Analytics",    "description": "Real-time BSR tracking, competitor price monitoring, market share analytics, and profit P&L.",       "price_per_seat": 249.0},
        {"product_id": "AMZ-ENT",        "product_name": "Enterprise Seller Suite",         "category": "Platform",     "description": "Full-service account management: ads, FBA, listing, brand, analytics, dedicated AM, QBRs.",         "price_per_seat": 1999.0},
    ]
    p4 = _write_csv(tenant_id, "product_catalog", [
        "product_id", "product_name", "category", "description", "price_per_seat"
    ], catalog)
    print("  Catalog:", p4)

    print(f"\nAmazon E-commerce dataset generated for tenant [{tenant_id}]")
    return {
        "sellers": len(sellers),
        "metrics": len(metrics),
        "tickets": len(tickets),
        "catalog": len(catalog),
    }


if __name__ == "__main__":
    generate_amazon_dataset("amazon")
