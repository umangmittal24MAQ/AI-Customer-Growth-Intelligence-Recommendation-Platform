"""
Generates a simple, easy-to-follow sports-retail demo tenant ("sportyzone"),
styled like a Decathlon-type sporting goods retailer, instead of the
SaaS/subscription-flavored demo tenants elsewhere in this folder.

Why this exists: the SaaS-seat model ("plan_tier"/"seats"/"price_per_seat")
is hard for a non-technical reviewer to eyeball and sanity-check. A sports
retailer is something anyone can reason about instantly: "this store mostly
stocks/sells badminton gear -> recommend badminton shoes" is obvious in a
way "Growth plan -> Scale plan" isn't.

Produces, for tenant_id="sportyzone":
  - product_catalog.csv  -- 60 real sporting-goods products across 10
    categories (Badminton, Running, Cricket, Football, Gym & Strength,
    Cycling, Swimming, Yoga & Fitness, Camping & Hiking, Team Sportswear).
    Each category has an entry-level item, a pro/upgrade item, and a few
    complementary accessories (e.g. Badminton Racket -> Court Shoes,
    Shuttlecocks, Grip Tape) so cross-sell has an obvious, checkable answer.
  - customers.csv -- 100 retail store accounts, each currently stocking one
    specific catalog product as their "plan_tier" (their current product).
  - usage_metrics.csv -- 4 months of activity per store.
  - support_tickets.csv -- a handful of complaints/requests.

Also writes directly into the DB (customers/catalog/usage/tickets) AND
seeds one recommendation per customer -- a same-category complementary or
upgrade product, with a confidence score derived from that store's engagement
-- so the UI has a populated, meaningful "currently stocks X -> we'd
recommend Y" view immediately, without requiring a live LLM pipeline run.
Running "Analyze Customer" afterward (if IndiaAI keys are configured)
will overwrite these with the agent pipeline's real output; until then,
these seeded rows are clearly checkable against the catalog by hand.

Usage:
    python data/generate_sportyzone_demo.py
"""

import json
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faker import Faker

fake = Faker()
random.seed(11)

HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, "tenant_uploads")
TENANT_ID = "sportyzone"

NUM_CUSTOMERS = 50

# ---------------------------------------------------------------------------
# Catalog: 10 categories. Each has an entry item + a pro/upgrade item, plus
# 2-4 complementary accessories. "complements" lists the obvious cross-sell
# partners by name so the mapping is checkable just by reading the CSV.
# ---------------------------------------------------------------------------
CATEGORIES = {
    "Badminton": [
        ("Badminton Starter Racket", 1, 18.0, "Lightweight aluminum racket for beginners just picking up badminton.", "Badminton Court Shoes, Shuttlecock Pack (Pack of 6)"),
        ("Badminton Pro Racket", 3, 89.0, "Carbon-fiber racket for competitive badminton players wanting more power and control.", "Badminton Court Shoes, Grip Tape, Shuttlecock Pack (Pack of 12)"),
        ("Badminton Court Shoes", 1, 42.0, "Non-marking indoor court shoes built for quick lateral movement in badminton.", "Badminton Pro Racket, Ankle Support Sleeve"),
        ("Shuttlecock Pack (Pack of 6)", 1, 9.0, "Feather shuttlecocks for casual and club-level badminton play.", "Badminton Starter Racket"),
        ("Shuttlecock Pack (Pack of 12)", 2, 16.0, "Tournament-grade feather shuttlecocks for competitive play.", "Badminton Pro Racket"),
        ("Grip Tape", 1, 6.0, "Sweat-absorbing grip tape for badminton and other racket sports.", "Badminton Pro Racket, Badminton Starter Racket"),
    ],
    "Running": [
        ("Running Shoes - Entry", 1, 45.0, "Cushioned everyday running shoes for beginner to casual runners.", "Running Socks (3-Pack), Running Shorts"),
        ("Running Shoes - Pro Marathon", 3, 140.0, "Carbon-plated racing shoes built for marathon and race-day performance.", "Compression Socks, GPS Running Watch"),
        ("Running Shorts", 1, 22.0, "Breathable lightweight shorts with liner, built for long runs.", "Running Shoes - Entry"),
        ("Running Socks (3-Pack)", 1, 12.0, "Blister-resistant running socks with arch support.", "Running Shoes - Entry, Running Shoes - Pro Marathon"),
        ("Compression Socks", 2, 19.0, "Graduated compression socks for recovery after long-distance runs.", "Running Shoes - Pro Marathon"),
        ("GPS Running Watch", 3, 199.0, "Wrist GPS watch tracking pace, distance, and heart rate.", "Running Shoes - Pro Marathon"),
    ],
    "Cricket": [
        ("Cricket Bat - Willow Starter", 1, 55.0, "Kashmir willow bat suited for club-level and weekend cricket.", "Cricket Batting Gloves, Cricket Helmet"),
        ("Cricket Bat - English Willow Pro", 3, 220.0, "Grade 1 English willow bat for serious club and league players.", "Cricket Batting Gloves, Cricket Pads"),
        ("Cricket Batting Gloves", 1, 28.0, "Padded batting gloves protecting fingers and knuckles at the crease.", "Cricket Bat - Willow Starter, Cricket Bat - English Willow Pro"),
        ("Cricket Pads", 2, 48.0, "Lightweight leg pads for batting protection.", "Cricket Bat - English Willow Pro"),
        ("Cricket Helmet", 2, 65.0, "Protective helmet with adjustable grille for batting and close fielding.", "Cricket Bat - Willow Starter"),
    ],
    "Football": [
        ("Football Boots - Firm Ground", 1, 38.0, "Firm-ground football boots for natural grass pitches, entry level.", "Football Socks, Shin Guards"),
        ("Football Boots - Pro FG", 3, 130.0, "Lightweight pro-level firm-ground boots for competitive matches.", "Shin Guards, Football Socks"),
        ("Shin Guards", 1, 14.0, "Lightweight shin guards with ankle protection.", "Football Boots - Firm Ground, Football Boots - Pro FG"),
        ("Football Socks", 1, 8.0, "Cushioned football socks with grip zones.", "Football Boots - Firm Ground"),
        ("Match Football (Size 5)", 1, 25.0, "Official size 5 match football for club and league play.", "Football Boots - Pro FG"),
    ],
    "Gym & Strength": [
        ("Adjustable Dumbbell Set", 1, 75.0, "Space-saving adjustable dumbbells for home strength training.", "Weightlifting Gloves, Yoga Mat"),
        ("Olympic Barbell Set", 3, 260.0, "Full Olympic barbell and plate set for serious strength training.", "Weightlifting Belt, Weightlifting Gloves"),
        ("Weightlifting Gloves", 1, 15.0, "Padded gloves protecting grip during weight training.", "Adjustable Dumbbell Set, Olympic Barbell Set"),
        ("Weightlifting Belt", 2, 32.0, "Support belt for heavy squats and deadlifts.", "Olympic Barbell Set"),
        ("Resistance Band Set", 1, 18.0, "Set of 5 resistance bands for strength and mobility work.", "Adjustable Dumbbell Set"),
    ],
    "Cycling": [
        ("Road Bike - Entry", 1, 320.0, "Aluminum-frame road bike for new cyclists and commuting.", "Cycling Helmet, Bike Repair Kit"),
        ("Road Bike - Carbon Pro", 3, 1450.0, "Carbon-frame road bike for serious road cyclists.", "Cycling Helmet, Cycling Computer"),
        ("Cycling Helmet", 1, 45.0, "Ventilated helmet with adjustable fit for road cycling.", "Road Bike - Entry, Road Bike - Carbon Pro"),
        ("Bike Repair Kit", 1, 22.0, "Puncture repair kit with tire levers and mini pump.", "Road Bike - Entry"),
        ("Cycling Computer", 2, 58.0, "Handlebar computer tracking speed, distance, and cadence.", "Road Bike - Carbon Pro"),
    ],
    "Swimming": [
        ("Swimsuit - Training", 1, 26.0, "Chlorine-resistant training swimsuit for regular pool sessions.", "Swim Goggles, Swim Cap"),
        ("Wetsuit - Open Water", 3, 180.0, "Buoyant wetsuit for open-water swimming and triathlon training.", "Swim Goggles, Swim Tow Float"),
        ("Swim Goggles", 1, 12.0, "Anti-fog swim goggles with UV protection.", "Swimsuit - Training, Wetsuit - Open Water"),
        ("Swim Cap", 1, 5.0, "Silicone swim cap reducing drag in the pool.", "Swimsuit - Training"),
        ("Swim Tow Float", 2, 20.0, "High-visibility tow float for open-water swim safety.", "Wetsuit - Open Water"),
    ],
    "Yoga & Fitness": [
        ("Yoga Mat - Standard", 1, 20.0, "Non-slip 6mm yoga mat for studio or home practice.", "Yoga Blocks, Yoga Strap"),
        ("Yoga Mat - Pro Alignment", 2, 55.0, "Alignment-marked premium mat for serious yoga practitioners.", "Yoga Blocks, Yoga Strap"),
        ("Yoga Blocks (Set of 2)", 1, 14.0, "Foam blocks for support and alignment in yoga poses.", "Yoga Mat - Standard, Yoga Mat - Pro Alignment"),
        ("Yoga Strap", 1, 8.0, "Stretch strap for improving flexibility in yoga practice.", "Yoga Mat - Standard"),
        ("Fitness Tracker Band", 2, 60.0, "Wrist band tracking steps, heart rate, and workout sessions.", "Yoga Mat - Pro Alignment"),
    ],
    "Camping & Hiking": [
        ("Hiking Boots - Entry", 1, 55.0, "Waterproof hiking boots for day hikes and light trails.", "Hiking Backpack, Trekking Poles"),
        ("Hiking Boots - Pro Trail", 3, 165.0, "Rugged hiking boots for multi-day treks and rough terrain.", "Hiking Backpack, Trekking Poles"),
        ("Hiking Backpack 40L", 1, 68.0, "Multi-day hiking backpack with rain cover and hydration sleeve.", "Hiking Boots - Entry, Hiking Boots - Pro Trail"),
        ("Trekking Poles (Pair)", 1, 30.0, "Adjustable trekking poles for stability on hilly trails.", "Hiking Boots - Pro Trail"),
        ("2-Person Tent", 2, 95.0, "Lightweight 2-person tent for weekend camping trips.", "Hiking Backpack 40L"),
    ],
    "Team Sportswear": [
        ("Team Jersey - Standard", 1, 24.0, "Breathable team jersey for club-level matches and training.", "Team Shorts, Team Socks"),
        ("Team Jersey - Pro Match", 2, 55.0, "Match-day jersey with moisture-wicking pro fabric.", "Team Shorts, Team Socks"),
        ("Team Shorts", 1, 15.0, "Matching team shorts for training and match day.", "Team Jersey - Standard, Team Jersey - Pro Match"),
        ("Team Socks", 1, 7.0, "Matching team socks, sold by the set.", "Team Jersey - Standard"),
        ("Team Training Bibs (Set of 10)", 1, 40.0, "Set of 10 colored bibs for training-ground scrimmages.", "Team Jersey - Standard"),
    ],
}

CATEGORY_LIST = list(CATEGORIES.keys())


def _write_csv(dataset_label: str, fieldnames: list[str], rows: list[dict]) -> str:
    import csv
    tenant_dir = os.path.join(OUT_DIR, TENANT_ID)
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


def build_catalog():
    """Returns list of catalog dicts, using internal field names directly."""
    rows = []
    pid = 1
    for category, items in CATEGORIES.items():
        for name, tier, price, description, complements in items:
            rows.append({
                "product_id": f"SZ-{pid:04d}",
                "product_name": name,
                "tier_level": tier,
                "price_per_seat": price,
                "complements": complements,
                "category": category,
                "description": description,
            })
            pid += 1
    return rows


def build_customers(catalog):
    """100 store accounts. Each store currently stocks ONE specific catalog
    product as its 'plan_tier' -- almost always an entry-level (tier 1) item
    within a category, so there's an obvious upgrade/cross-sell path for the
    recommendation to point at."""
    by_category = {}
    for p in catalog:
        by_category.setdefault(p["category"], []).append(p)

    customers = []
    for i in range(NUM_CUSTOMERS):
        category = CATEGORY_LIST[i % len(CATEGORY_LIST)]
        entry_items = [p for p in by_category[category] if p["tier_level"] == 1] or by_category[category]
        primary_name = CATEGORIES[category][0][0]
        primary_item = next((p for p in entry_items if p["product_name"] == primary_name), None)
        # Weight toward the category's flagship item (racket/shoes/bat/etc.)
        # most of the time so the demo mostly shows the obvious "bought the
        # main gear -> recommend the natural companion item" story, with a
        # minority of stores instead currently stocking an accessory first
        # (a more realistic long-tail case).
        if primary_item and random.random() < 0.7:
            current_product = primary_item
        else:
            current_product = random.choice(entry_items)
        seats = random.randint(5, 150)  # units currently stocked
        customers.append({
            "customer_id": f"SZ-STORE-{i:04d}",
            "customer_name": f"{fake.city()} {category.split(' ')[0]} Store" if random.random() < 0.5 else fake.company(),
            "industry": category,
            "plan_tier": current_product["product_name"],
            "seats": seats,
            "renewal_date": (date.today() + timedelta(days=random.randint(10, 380))).isoformat(),
            "account_manager": fake.name(),
            "_category": category,
            "_current_product": current_product,
        })
    return customers


def build_usage(customers):
    rows = []
    for c in customers:
        base = random.randint(25, 95)
        drift = random.choice([-1, -1, 0, 1, 1, 1])
        for idx, month in enumerate(_months_back(4)):
            score = max(5, min(100, base + drift * idx * random.randint(2, 6)))
            rows.append({
                "customer_id": c["customer_id"],
                "month": month,
                # active_users/storage_used_gb/storage_limit_gb were dropped
                # here on purpose -- those are SaaS-specific concepts
                # (seat logins, storage quotas) that don't mean anything
                # for a sports-goods retail tenant, and previously got
                # filled with random filler numbers just to satisfy the
                # (now-optional) core schema. That's how a badminton
                # retailer ended up with a churn analysis narrating GB of
                # storage usage. monthly_orders is this tenant's actual,
                # domain-appropriate engagement signal -- schema-free
                # ingestion picks it up as a genuine discovered field
                # instead of a forced/fabricated core concept.
                "monthly_orders": max(1, int(c["seats"] * random.uniform(0.3, 0.95))),
                "feature_usage_score": score,
            })
    return rows


COMPLAINT_TYPES = ["delivery", "billing", "returns", "stock_shortage"]


def build_tickets(customers):
    rows = []
    tid = 1
    for c in customers:
        if random.random() < 0.4:
            rows.append({
                "ticket_id": f"SZ-TCK-{tid:05d}",
                "customer_id": c["customer_id"],
                "created_at": (date.today() - timedelta(days=random.randint(1, 90))).isoformat(),
                "category": random.choice(COMPLAINT_TYPES),
                "subject": fake.sentence(nb_words=6),
                "resolved": random.random() < 0.65,
            })
            tid += 1
    return rows


def pick_recommendation(customer, catalog):
    """Simple, checkable-by-eye cross-sell rule: same category, not the
    product they already stock, preferring something listed in that
    product's own 'complements' field, otherwise falling back to a
    higher-tier item in the same category. This is the SEEDED demo
    recommendation shown before any live agent run -- deliberately simple
    so a reviewer can verify it against the CSV without any reasoning
    beyond 'same sport, different item'."""
    current = customer["_current_product"]
    category = customer["_category"]
    complement_names = [n.strip() for n in (current.get("complements") or "").split(",") if n.strip()]

    candidates_by_name = {p["product_name"]: p for p in catalog if p["category"] == category}
    for name in complement_names:
        if name in candidates_by_name and name != current["product_name"]:
            return candidates_by_name[name]

    same_cat_other = [p for p in catalog if p["category"] == category and p["product_name"] != current["product_name"]]
    if same_cat_other:
        return max(same_cat_other, key=lambda p: p["tier_level"])
    return None


def seed_database(catalog, customers, usage_rows, ticket_rows):
    from datetime import datetime, timezone
    from app import db
    db.init_db()

    catalog_rows = [{k: v for k, v in p.items()} for p in catalog]
    db.upsert_product_catalog(TENANT_ID, catalog_rows)

    customer_rows = [
        {k: v for k, v in c.items() if not k.startswith("_")}
        for c in customers
    ]
    db.upsert_customers(TENANT_ID, customer_rows)
    db.upsert_usage_metrics(TENANT_ID, usage_rows)
    if ticket_rows:
        db.upsert_support_tickets(TENANT_ID, ticket_rows)

    # Recommendations have no natural unique key (see db.log_recommendation),
    # so re-running this script would otherwise just pile up duplicate rows
    # per customer with the same date-only generated_at -- ties that
    # get_latest_recommendations' MAX(generated_at) grouping can't reliably
    # break. Clear this tenant's prior recommendations first so a rerun
    # replaces them cleanly instead of stacking.
    conn = db.get_connection()
    conn.execute("DELETE FROM recommendations_log WHERE tenant_id = ?", (TENANT_ID,))
    conn.commit()
    conn.close()

    # Seed one recommendation per customer, confidence derived from that
    # store's average engagement (feature_usage_score) so scores vary
    # realistically instead of all landing on one flat number.
    usage_by_customer = {}
    for row in usage_rows:
        usage_by_customer.setdefault(row["customer_id"], []).append(row["feature_usage_score"])

    seeded = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for c in customers:
        rec_product = pick_recommendation(c, catalog)
        avg_engagement = sum(usage_by_customer.get(c["customer_id"], [50])) / max(1, len(usage_by_customer.get(c["customer_id"], [50])))
        confidence_score = max(20, min(92, round(avg_engagement * 0.9 + random.uniform(-5, 5))))
        rec = {
            "customer_id": c["customer_id"],
            "customer_name": c["customer_name"],
            "segment": "growth" if avg_engagement >= 55 else "at-risk",
            "churn_risk": "low" if avg_engagement >= 55 else "medium",
            "churn_reason": "Stable engagement based on recent sales activity." if avg_engagement >= 55 else "Engagement has softened recently -- worth a check-in.",
            "recommended_product": rec_product["product_name"] if rec_product else None,
            "recommendation_type": "cross_sell",
            "rationale": (
                f"This store currently stocks {c['plan_tier']} ({c['_category']}). "
                f"Based on typical {c['_category']} shopper patterns, {rec_product['product_name']} "
                f"is a natural complementary product to stock alongside it."
                if rec_product else "No complementary product found in this category."
            ),
            "revenue_score": confidence_score,
            "estimated_deal_value": round((rec_product["price_per_seat"] if rec_product else 0) * c["seats"] * 0.15, 2),
            "renewal_date": c["renewal_date"],
            "generated_at": now_iso,
            "agent_trace": {
                "agents_run": ["seed_script"],
                "note": "Seeded directly for demo purposes -- run 'Analyze Customer' to replace with a live agent pipeline result.",
            },
            "no_recommendation_reason_code": None,
        }
        db.log_recommendation(TENANT_ID, rec)
        seeded += 1
    return seeded


def main():
    catalog = build_catalog()
    customers = build_customers(catalog)
    usage_rows = build_usage(customers)
    ticket_rows = build_tickets(customers)

    # Write CSVs too, so the same data can be re-uploaded through the normal
    # onboarding flow / shown as "what a real upload looks like".
    _write_csv("product_catalog", list(catalog[0].keys()), catalog)
    clean_customers = [{k: v for k, v in c.items() if not k.startswith("_")} for c in customers]
    _write_csv("customers", list(clean_customers[0].keys()), clean_customers)
    _write_csv("usage_metrics", list(usage_rows[0].keys()), usage_rows)
    if ticket_rows:
        _write_csv("support_tickets", list(ticket_rows[0].keys()), ticket_rows)

    seeded = seed_database(catalog, customers, usage_rows, ticket_rows)

    print(f"Sportyzone demo tenant ready: {len(catalog)} catalog products, "
          f"{len(customers)} customers, {seeded} seeded recommendations.")
    print(f"CSV output: {os.path.join(OUT_DIR, TENANT_ID)}")
    print("Tenant ID to log in with: sportyzone")


if __name__ == "__main__":
    main()
