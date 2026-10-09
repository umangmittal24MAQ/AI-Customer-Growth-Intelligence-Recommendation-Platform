"""
Amazon Grocery Marketplace Demo Dataset Generator.
Generates CSVs for an Amazon Grocery / Fresh seller platform, where each
"customer" is a grocery brand/seller on the marketplace and upsell = getting
them to stock additional grocery product lines and services.

Mirrors the Amazon demo's 4-CSV shape exactly so the schema-free ingestion
pipeline treats it identically (customers / usage_metrics / support_tickets /
product_catalog).

Run: python data/generate_grocery_demo.py
Or:  generate_grocery_dataset(tenant_id="amazon-grocery")
"""

import csv
import os
import random
from datetime import date, timedelta

random.seed(777)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "tenant_uploads")
NUM_ENTITIES = 22

SELLER_NAMES = [
    "Fresh Valley Foods", "DailyBasket Grocers", "Organic Roots Co", "Pantry Prime Seller",
    "GreenLeaf Naturals", "MorningFresh Dairy", "Snack Central Hub", "PureHarvest Foods",
    "QuickCart Grocery", "Golden Grain Traders", "NutriPick Store", "FarmDirect Supply",
    "Sunrise Beverages", "HappyTummy Foods", "EliteGourmet Market", "Wholesome Bites Co",
    "SpiceWorld Traders", "FrozenDelights Seller", "PetFeast Supplies", "BabyCare Essentials",
    "CleanHome Grocers", "Everyday Staples Co",
]

ISSUE_TYPES = [
    "Cold Chain Break", "Expiry Compliance", "Stock Out",
    "Damaged Perishables", "Labeling Violation",
]

ISSUE_DESCS = [
    "Perishable shipment exceeded safe temperature window.",
    "Products flagged for near-expiry compliance review.",
    "High-demand SKU out of stock during promotion.",
    "Damaged perishable units reported on delivery.",
    "Nutrition labeling did not meet marketplace policy.",
    "Seller fulfillment rating dropped below threshold.",
    "Batch recall query on a packaged food item.",
]

# price_per_seat = onboarding/listing service cost per fulfillment lane;
# features = the SKUs / benefits bundled inside that grocery line/service.
CATALOG = [
    {"product_id": "GRO-STAPLE", "product_name": "Everyday Staples Line", "category": "Grocery",
     "description": "Core pantry staples product line.", "price_per_seat": 149.0,
     "features": "Rice & Flour Range|Cooking Oils|Sugar & Salt Packs|Bulk Restock Program"},
    {"product_id": "GRO-BEV",    "product_name": "Beverages Assortment", "category": "Beverages",
     "description": "Hot and cold beverage product line.", "price_per_seat": 179.0,
     "features": "Coffee & Tea Range|Juices & Soft Drinks|Energy Drinks|Chilled Display Support"},
    {"product_id": "GRO-SNACK",  "product_name": "Snacks & Confectionery", "category": "Snacks",
     "description": "Packaged snacks and chocolate line.", "price_per_seat": 169.0,
     "features": "Chips & Namkeen|Cookies & Biscuits|Chocolate Range|Impulse-Buy Placement"},
    {"product_id": "GRO-DAIRY",  "product_name": "Dairy & Chilled Line", "category": "Dairy",
     "description": "Refrigerated dairy product line.", "price_per_seat": 229.0,
     "features": "Milk & Yogurt|Cheese Range|Butter & Cream|Cold-Chain Logistics Kit"},
    {"product_id": "GRO-FROZEN", "product_name": "Frozen Foods Range", "category": "Frozen",
     "description": "Frozen ready-to-cook product line.", "price_per_seat": 249.0,
     "features": "Frozen Pizza & Nuggets|Ice Cream Range|Frozen Vegetables|Freezer Lane Setup"},
    {"product_id": "GRO-ORGANIC","product_name": "Organic & Natural Line", "category": "Organic",
     "description": "Certified organic grocery product line.", "price_per_seat": 299.0,
     "features": "Organic Grains|Cold-Pressed Oils|Natural Sweeteners|Organic Certification Badge"},
    {"product_id": "GRO-HOUSE",  "product_name": "Household Essentials", "category": "Household",
     "description": "Cleaning and home-care product line.", "price_per_seat": 159.0,
     "features": "Detergents & Cleaners|Tissue & Wipes|Dishwash Range|Multipack Bundle Program"},
    {"product_id": "GRO-PCARE",  "product_name": "Personal Care Line", "category": "Personal Care",
     "description": "Everyday personal care product line.", "price_per_seat": 189.0,
     "features": "Shampoo & Body Wash|Toothpaste Range|Face Wash|Cross-Category Placement"},
    {"product_id": "GRO-BABY",   "product_name": "Baby Care Range", "category": "Baby",
     "description": "Infant food and care product line.", "price_per_seat": 269.0,
     "features": "Diapers & Wipes|Infant Formula|Baby Food Jars|Parent Subscription Program"},
    {"product_id": "GRO-PET",    "product_name": "Pet Supplies Line", "category": "Pet",
     "description": "Pet food and treats product line.", "price_per_seat": 199.0,
     "features": "Dog & Cat Food|Pet Treats|Grooming Supplies|Auto-Replenish Program"},
    {"product_id": "GRO-SPICE",  "product_name": "Spices & Condiments", "category": "Grocery",
     "description": "Cooking spices and sauces product line.", "price_per_seat": 179.0,
     "features": "Whole & Ground Spices|Sauces & Ketchup|Pickles & Pastes|Regional Cuisine Kit"},
    {"product_id": "GRO-BAKERY", "product_name": "Bakery & Breakfast", "category": "Bakery",
     "description": "Bread, cereal and breakfast product line.", "price_per_seat": 189.0,
     "features": "Bread & Buns|Breakfast Cereals|Jams & Spreads|Fresh Bakery Logistics"},
    {"product_id": "GRO-HEALTH", "product_name": "Health & Wellness Foods", "category": "Health",
     "description": "Nutrition and wellness product line.", "price_per_seat": 279.0,
     "features": "Protein & Supplements|Sugar-Free Range|Superfoods|Wellness Advisor Program"},
    {"product_id": "GRO-ADS",    "product_name": "Sponsored Grocery Ads", "category": "Advertising",
     "description": "Marketplace ad and promotion service.", "price_per_seat": 399.0,
     "features": "Sponsored Product Ads|Deal-of-the-Day Slots|Coupon Campaigns|Ad Performance Reports"},
    {"product_id": "GRO-FRESH",  "product_name": "Fresh Produce Program", "category": "Produce",
     "description": "Fruits and vegetables fulfillment line.", "price_per_seat": 329.0,
     "features": "Fruits & Vegetables Range|Same-Day Fresh Delivery|Quality Grading|Wastage Recovery Support"},
    {"product_id": "GRO-ANALYTICS","product_name": "Grocery Analytics Dashboard", "category": "Analytics",
     "description": "Sales and demand analytics service.", "price_per_seat": 249.0,
     "features": "Demand Forecasting|Basket Analysis|Competitor Price Tracking|Custom Reports"},
    {"product_id": "GRO-SUB",    "product_name": "Subscribe & Save Program", "category": "Strategy",
     "description": "Recurring subscription order service.", "price_per_seat": 219.0,
     "features": "Auto-Delivery Setup|Loyalty Discounts|Retention Analytics|Churn-Reduction Toolkit"},
    {"product_id": "GRO-PRO",    "product_name": "Grocery Pro Seller Suite", "category": "Platform",
     "description": "Full-service grocery account package.", "price_per_seat": 1599.0,
     "features": "All Product Lines Access|Dedicated Account Manager|Cold-Chain Priority|Quarterly Business Reviews|Compliance Support"},
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


def generate_grocery_dataset(tenant_id="amazon-grocery"):
    tiers = ["Individual", "Professional", "Enterprise"]
    product_names = [p["product_name"] for p in CATALOG]

    # 1. Grocery sellers (entity/customer file)
    # 'seats' = number of fulfillment lanes/warehouses, drives deal value.
    sellers = []
    for i in range(NUM_ENTITIES):
        name = SELLER_NAMES[i] if i < len(SELLER_NAMES) else f"Grocery Seller {i:04d}"
        tier = random.choice(tiers)
        seats = {"Individual": random.randint(1, 2),
                 "Professional": random.randint(2, 5),
                 "Enterprise": random.randint(5, 15)}[tier]
        sellers.append({
            "seller_id": f"GRO-{i:04d}",
            "store_name": name,
            "subscription_tier": tier,
            "industry": random.choice(
                ["Grocery", "Beverages", "Snacks", "Dairy", "Frozen", "Organic", "Household"]),
            "current_product": random.choice(product_names),
            "seats": seats,
            "active_skus": random.randint(50, 4000),
            "seller_rating": round(random.uniform(3.2, 5.0), 1),
            "account_health": random.choice(["Good", "Good", "Good", "At Risk", "Critical"]),
            "renewal_date": (date.today() + timedelta(days=random.randint(30, 365))).isoformat(),
        })
    p1 = _write_csv(tenant_id, "grocery_sellers", list(sellers[0].keys()), sellers)
    print("  Sellers:", p1)

    # 2. Monthly grocery metrics (usage file)
    metrics = []
    for s in sellers:
        base = random.randint(15000, 260000)
        # Drift spread deliberately lands trends in all three churn bands:
        # <=-15% HIGH, -1%..-14% MEDIUM, >=0% LOW (trend = drift * 5 months).
        drift = random.choice([-0.10, -0.08, -0.05, -0.025, -0.02, -0.012, 0, 0, 0.05, 0.10])
        for idx, month in enumerate(_months_back(6)):
            sales = max(2000, int(base * (1 + drift * idx)))
            metrics.append({
                "seller_id": s["seller_id"],
                "reporting_month": month,
                "monthly_gmv_usd": sales,
                "units_sold": random.randint(500, 40000),
                "avg_basket_size_usd": round(random.uniform(15, 120), 2),
                "promo_spend_usd": round(sales * random.uniform(0.05, 0.2), 2),
                "spoilage_rate_pct": round(random.uniform(0.5, 8.0), 1),
                "on_time_delivery_pct": round(random.uniform(80, 99), 1),
                "return_rate_pct": round(random.uniform(1.0, 10.0), 1),
            })
    p2 = _write_csv(tenant_id, "grocery_metrics", list(metrics[0].keys()), metrics)
    print("  Metrics:", p2)

    # 3. Support tickets (issues file)
    tickets = []
    for s in sellers:
        if random.random() < 0.6:
            opened = date.today() - timedelta(days=random.randint(1, 90))
            tickets.append({
                "seller_id": s["seller_id"],
                "issue_type": random.choice(ISSUE_TYPES),
                "severity": random.choice(["low", "medium", "medium", "high"]),
                "description": random.choice(ISSUE_DESCS),
                "opened_date": opened.isoformat(),
                "resolved": random.random() < 0.65,
            })
    if tickets:
        p3 = _write_csv(tenant_id, "support_tickets", list(tickets[0].keys()), tickets)
        print("  Tickets:", p3)

    # 4. Product catalog — grocery product lines available to upsell
    p4 = _write_csv(tenant_id, "product_catalog",
                    ["product_id", "product_name", "category", "description", "price_per_seat", "features"],
                    CATALOG)
    print("  Catalog:", p4)

    print(f"\nAmazon Grocery dataset generated for tenant [{tenant_id}]")
    return {
        "sellers": len(sellers),
        "metrics": len(metrics),
        "tickets": len(tickets),
        "catalog": len(CATALOG),
    }


if __name__ == "__main__":
    generate_grocery_dataset("amazon-grocery")
