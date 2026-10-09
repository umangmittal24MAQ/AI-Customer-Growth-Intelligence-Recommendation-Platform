"""
L'Oreal Beauty Retail Demo Dataset Generator.
Generates CSVs for a L'Oreal retail-partner / salon distribution platform,
where each "customer" is a retail partner/salon that stocks L'Oreal product
lines, and upsell = getting them to carry additional product lines.

Mirrors the Amazon demo's 4-CSV shape exactly so the schema-free ingestion
pipeline treats it identically (customers / usage_metrics / support_tickets /
product_catalog).

Run: python data/generate_loreal_demo.py
Or:  generate_loreal_dataset(tenant_id="loreal")
"""

import csv
import os
import random
from datetime import date, timedelta

random.seed(2024)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "tenant_uploads")
NUM_ENTITIES = 22

PARTNER_NAMES = [
    "Glamour Salon & Spa", "BeautyMart Retail", "Chic Hair Studio", "Radiance Beauty Bar",
    "Urban Cuts Salon", "Elegance Cosmetics Store", "Luxe Skin Clinic", "Style Avenue Salon",
    "Bloom Beauty Boutique", "Prime Looks Studio", "Velvet Touch Salon", "Aura Beauty House",
    "Mirror Image Salon", "Rose Petal Cosmetics", "The Grooming Lounge", "Serene Spa Retail",
    "Golden Glow Beauty", "Trendset Hair Studio", "Pure Bliss Salon", "Crown Beauty Depot",
    "Opal Skincare Store", "Nova Beauty Collective",
]

ISSUE_TYPES = [
    "Stock Shortage", "Damaged Shipment", "Pricing Dispute",
    "Promo Material Delay", "Product Recall Query",
]

ISSUE_DESCS = [
    "Requested restock not fulfilled within SLA window.",
    "Shipment arrived with damaged retail units.",
    "Wholesale pricing tier mismatch on latest invoice.",
    "In-store promotional display kit delayed.",
    "Query on batch recall for a discontinued shade.",
    "Partner margin dropped below agreed threshold.",
    "Cold-chain break suspected on skincare serums.",
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


# price_per_seat = wholesale onboarding cost per store location for that line;
# features = the SKUs / benefits bundled inside that product line.
CATALOG = [
    {"product_id": "LOR-ELV-SH",   "product_name": "Elvive Total Repair Shampoo Line", "category": "Haircare",
     "description": "Reparative shampoo range for damaged hair.", "price_per_seat": 149.0,
     "features": "Total Repair 5 Shampoo|Anti-Breakage Formula|Salon Retail Display|Bulk Restock Program"},
    {"product_id": "LOR-ELV-CN",   "product_name": "Elvive Total Repair Conditioner Line", "category": "Haircare",
     "description": "Matching conditioner and hair mask range.", "price_per_seat": 149.0,
     "features": "Total Repair Conditioner|Reparative Hair Mask|Leave-In Serum|Cross-Sell Bundle Kit"},
    {"product_id": "LOR-ELV-SER",  "product_name": "Elvive Hyaluron Plump Serum", "category": "Haircare",
     "description": "Hydrating hair serum with hyaluronic acid.", "price_per_seat": 199.0,
     "features": "72H Hydration Serum|Plumping Hair Care|Scalp Treatment|Sample Sachet Program"},
    {"product_id": "LOR-DREAM",    "product_name": "Elvive Dream Lengths Treatment", "category": "Haircare",
     "description": "Long-hair repair and anti-split-end treatment.", "price_per_seat": 179.0,
     "features": "No-Haircut Cream|Split-End Sealer|Length Repair Mask|Retail Merchandising Kit"},
    {"product_id": "LOR-PREF",     "product_name": "Preference Hair Color Range", "category": "Hair Color",
     "description": "At-home permanent hair color line.", "price_per_seat": 249.0,
     "features": "12-Week Fade-Defy Color|40+ Shade Range|Shade Consultation Chart|In-Store Color Bar"},
    {"product_id": "LOR-EXCEL",    "product_name": "Excellence Creme Color Line", "category": "Hair Color",
     "description": "Triple-protection permanent color range.", "price_per_seat": 269.0,
     "features": "Triple Care Color|Grey Coverage Formula|Pre-Color Serum|Colorist Training Session"},
    {"product_id": "LOR-SALON",    "product_name": "Professional Salon Color Kit", "category": "Professional",
     "description": "Salon-grade color and developer system.", "price_per_seat": 599.0,
     "features": "Majirel Color System|Oxydant Developer Range|Salon Colorist Certification|Priority Trade Support"},
    {"product_id": "LOR-REVIT-SER","product_name": "Revitalift Anti-Aging Serum", "category": "Skincare",
     "description": "Pro-retinol and vitamin C anti-aging serum.", "price_per_seat": 299.0,
     "features": "Pro-Retinol Serum|Vitamin C Booster|Wrinkle-Correct Formula|Beauty Advisor Kit"},
    {"product_id": "LOR-REVIT-CR", "product_name": "Revitalift Day & Night Cream", "category": "Skincare",
     "description": "Anti-wrinkle day and night moisturizer set.", "price_per_seat": 259.0,
     "features": "Hydrating Day Cream|Regenerating Night Cream|SPF 30 Protection|Gift-With-Purchase Program"},
    {"product_id": "LOR-AGE",      "product_name": "Age Perfect Skincare Set", "category": "Skincare",
     "description": "Mature-skin care and firming range.", "price_per_seat": 289.0,
     "features": "Rosy Tone Moisturizer|Cell Renewal Serum|Eye Renewal Cream|Mature-Skin Consultation Guide"},
    {"product_id": "LOR-TRUE",     "product_name": "True Match Foundation Line", "category": "Makeup",
     "description": "Skin-matching liquid foundation range.", "price_per_seat": 229.0,
     "features": "45-Shade Foundation|Shade-Finder Tool|Super Blendable Formula|In-Store Match Station"},
    {"product_id": "LOR-INFAL",    "product_name": "Infallible Matte Foundation", "category": "Makeup",
     "description": "24-hour long-wear matte foundation.", "price_per_seat": 219.0,
     "features": "24H Long-Wear|Transfer-Proof Matte|Full Coverage Formula|Tester Unit Program"},
    {"product_id": "LOR-MASC",     "product_name": "Voluminous Mascara Range", "category": "Makeup",
     "description": "Volumizing and lengthening mascara line.", "price_per_seat": 189.0,
     "features": "Lash Paradise Mascara|Volume Building Formula|Waterproof Option|Eye-Look Display Stand"},
    {"product_id": "LOR-LIP",      "product_name": "Colour Riche Lipstick Line", "category": "Makeup",
     "description": "Moisturizing satin-finish lipstick range.", "price_per_seat": 199.0,
     "features": "Satin Finish Lipstick|30+ Shade Range|Nourishing Oil Formula|Lip Bar Merchandising"},
    {"product_id": "LOR-MEN",      "product_name": "Men Expert Grooming Line", "category": "Men",
     "description": "Men's skincare and grooming range.", "price_per_seat": 209.0,
     "features": "Hydra Energetic Moisturizer|Anti-Fatigue Serum|Charcoal Face Wash|Men's Section Setup"},
    {"product_id": "LOR-PARADISE", "product_name": "Paradise Enriched Serum Line", "category": "Skincare",
     "description": "Antioxidant floral facial serum range.", "price_per_seat": 279.0,
     "features": "Floral Extract Serum|Antioxidant Boost|Radiance Treatment|Premium Retail Placement"},
    {"product_id": "LOR-TAN",      "product_name": "Sublime Bronze Self-Tan Range", "category": "Skincare",
     "description": "Streak-free self-tanning product line.", "price_per_seat": 169.0,
     "features": "Self-Tanning Serum|Streak-Free Mousse|Gradual Glow Lotion|Seasonal Promo Kit"},
    {"product_id": "LOR-PRO-SUITE","product_name": "L'Oreal Pro Partner Suite", "category": "Platform",
     "description": "Full multi-line distribution and training package.", "price_per_seat": 1499.0,
     "features": "All Product Lines Access|Dedicated Trade Manager|Quarterly Business Reviews|Priority Restock SLA|Staff Training Program"},
]


def generate_loreal_dataset(tenant_id="loreal"):
    tiers = ["Boutique", "Retail", "Flagship"]
    channels = ["Salon", "Pharmacy", "Department Store", "Specialty Beauty", "E-commerce"]
    product_names = [p["product_name"] for p in CATALOG]

    # 1. Retail partners (entity/customer file)
    # 'seats' = number of store locations, drives deal-value (price_per_seat * seats * 12)
    partners = []
    for i in range(NUM_ENTITIES):
        name = PARTNER_NAMES[i] if i < len(PARTNER_NAMES) else f"Beauty Partner {i:04d}"
        tier = random.choice(tiers)
        seats = {"Boutique": random.randint(1, 2),
                 "Retail": random.randint(2, 6),
                 "Flagship": random.randint(5, 20)}[tier]
        partners.append({
            "partner_id": f"LOR-{i:04d}",
            "partner_name": name,
            "subscription_tier": tier,
            "industry": random.choice(channels),
            "current_product": random.choice(product_names),
            "seats": seats,
            "active_skus": random.randint(20, 600),
            "partner_rating": round(random.uniform(3.2, 5.0), 1),
            "account_health": random.choice(["Good", "Good", "Good", "At Risk", "Critical"]),
            "renewal_date": (date.today() + timedelta(days=random.randint(30, 365))).isoformat(),
        })
    p1 = _write_csv(tenant_id, "loreal_partners", list(partners[0].keys()), partners)
    print("  Partners:", p1)

    # 2. Monthly sell-through metrics (usage file)
    metrics = []
    for s in partners:
        base = random.randint(12000, 220000)
        # Drift spread deliberately lands trends in all three churn bands:
        # <=-15% HIGH, -1%..-14% MEDIUM, >=0% LOW (trend = drift * 5 months).
        drift = random.choice([-0.10, -0.08, -0.05, -0.025, -0.02, -0.012, 0, 0, 0.05, 0.10])
        for idx, month in enumerate(_months_back(6)):
            sales = max(2000, int(base * (1 + drift * idx)))
            metrics.append({
                "partner_id": s["partner_id"],
                "reporting_month": month,
                "monthly_sell_through_usd": sales,
                "inventory_units_on_hand": random.randint(200, 5000),
                "reorder_frequency_days": random.randint(15, 90),
                "promo_spend_usd": round(sales * random.uniform(0.04, 0.18), 2),
                "shelf_share_pct": round(random.uniform(10, 60), 1),
                "return_rate_pct": round(random.uniform(1.0, 12.0), 1),
                "customer_satisfaction_pct": round(random.uniform(70, 98), 1),
            })
    p2 = _write_csv(tenant_id, "partner_metrics", list(metrics[0].keys()), metrics)
    print("  Metrics:", p2)

    # 3. Support tickets (issues file)
    tickets = []
    for s in partners:
        if random.random() < 0.6:
            opened = date.today() - timedelta(days=random.randint(1, 90))
            tickets.append({
                "partner_id": s["partner_id"],
                "issue_type": random.choice(ISSUE_TYPES),
                "severity": random.choice(["low", "medium", "medium", "high"]),
                "description": random.choice(ISSUE_DESCS),
                "opened_date": opened.isoformat(),
                "resolved": random.random() < 0.65,
            })
    if tickets:
        p3 = _write_csv(tenant_id, "support_tickets", list(tickets[0].keys()), tickets)
        print("  Tickets:", p3)

    # 4. Product catalog — L'Oreal product lines available to upsell
    p4 = _write_csv(tenant_id, "product_catalog",
                    ["product_id", "product_name", "category", "description", "price_per_seat", "features"],
                    CATALOG)
    print("  Catalog:", p4)

    print(f"\nL'Oreal beauty dataset generated for tenant [{tenant_id}]")
    return {
        "partners": len(partners),
        "metrics": len(metrics),
        "tickets": len(tickets),
        "catalog": len(CATALOG),
    }


if __name__ == "__main__":
    generate_loreal_dataset("loreal")
