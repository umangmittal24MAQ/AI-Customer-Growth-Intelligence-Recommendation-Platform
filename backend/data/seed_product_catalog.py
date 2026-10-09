"""
Seeds the product_catalog table with a fixed, deliberately designed set of
products. The LLM will only ever recommend from this list — it never invents
products, which keeps output constrained and demoable.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "upsell.db")

PRODUCTS = [
    # (product_id, name, tier_level, price_per_seat, complements, category, description)

    # --- core-plan (unchanged from original 12) ---
    ("PROD-001", "Business Standard", 1, 12.50, "PROD-004,PROD-005", "core-plan",
     "Entry-level productivity suite with email, chat, and file storage."),
    ("PROD-002", "E1", 1, 10.00, "PROD-004", "core-plan",
     "Web-only productivity apps and email, no desktop installs."),
    ("PROD-003", "E3", 2, 23.00, "PROD-004,PROD-005,PROD-006", "core-plan",
     "Full desktop apps, device management, and information protection."),
    ("PROD-004", "E5", 3, 38.00, "PROD-006,PROD-007", "core-plan",
     "Top-tier plan bundling advanced security, compliance, and analytics."),
    ("PROD-005", "Security Add-on (Defender)", 2, 5.50, "PROD-003,PROD-004", "security",
     "Endpoint threat protection, malware defense, and security alerts."),
    ("PROD-006", "Advanced Analytics Add-on", 2, 6.00, "PROD-003,PROD-004", "analytics",
     "Usage dashboards, custom reports, and data visualization tools."),
    ("PROD-007", "Compliance & eDiscovery Add-on", 3, 8.00, "PROD-004", "security",
     "Legal hold, audit logging, data loss prevention, and regulatory compliance."),
    ("PROD-008", "Additional Storage Pack (1TB)", 1, 3.00, "PROD-001,PROD-002,PROD-003", "storage",
     "Extra cloud storage capacity for files and mailboxes running low on space."),
    ("PROD-009", "Voice/Calling Add-on", 2, 8.50, "PROD-003,PROD-004", "communications",
     "VoIP calling, phone system integration, and call routing."),
    ("PROD-010", "Premium Support Plan", 2, 4.00, "PROD-003,PROD-004,PROD-005", "support",
     "Priority ticket response, dedicated support engineer, faster SLAs."),
    ("PROD-011", "AI Copilot Add-on", 3, 30.00, "PROD-003,PROD-004", "analytics",
     "AI-assisted drafting, summarization, and performance insights."),
    ("PROD-012", "Backup & Recovery Add-on", 2, 4.50, "PROD-001,PROD-002,PROD-003", "storage",
     "Automated backups and point-in-time recovery for files and mailboxes."),

    # --- core-plan (additional tiers/bundles) ---
    ("PROD-013", "Business Essentials", 1, 8.00, "PROD-008,PROD-010", "core-plan",
     "Lightweight core plan with shared mailboxes and basic file sharing for small teams."),
    ("PROD-014", "Business Premium", 2, 18.00, "PROD-005,PROD-006,PROD-009", "core-plan",
     "Mid-tier plan adding device management and advanced threat protection to Business Standard."),
    ("PROD-015", "F3 Frontline", 1, 9.00, "PROD-008,PROD-009", "core-plan",
     "Shift-based plan for frontline/deskless workers with mobile-first apps."),
    ("PROD-016", "E3 Government", 2, 25.00, "PROD-005,PROD-007", "core-plan",
     "E3-equivalent plan with government-community-cloud compliance boundaries."),
    ("PROD-017", "Nonprofit Standard", 1, 6.00, "PROD-006,PROD-008", "core-plan",
     "Discounted core productivity plan for registered nonprofit organizations."),
    ("PROD-018", "Education A3", 2, 11.00, "PROD-006,PROD-011", "core-plan",
     "Education-tier plan with classroom collaboration tools and device management."),

    # --- security ---
    ("PROD-019", "Identity & Access Add-on", 2, 6.50, "PROD-003,PROD-004,PROD-005", "security",
     "Multi-factor authentication, conditional access, and single sign-on."),
    ("PROD-020", "Insider Risk Management Add-on", 3, 9.00, "PROD-004,PROD-007", "security",
     "Detects and investigates risky user activity like data exfiltration."),
    ("PROD-021", "Advanced Threat Protection Plan 2", 3, 12.00, "PROD-005,PROD-004", "security",
     "Automated investigation and response for email and collaboration threats."),
    ("PROD-022", "Information Protection Add-on", 2, 7.00, "PROD-003,PROD-004", "security",
     "Sensitivity labels, encryption, and data classification for documents and email."),
    ("PROD-023", "Privileged Access Management", 3, 10.50, "PROD-004,PROD-019", "security",
     "Just-in-time elevated access controls for sensitive admin operations."),
    ("PROD-024", "Vulnerability Management Add-on", 2, 8.00, "PROD-005,PROD-021", "security",
     "Continuous asset discovery, risk scoring, and remediation tracking."),
    ("PROD-025", "Firewall & Network Protection Add-on", 2, 7.50, "PROD-005,PROD-021", "security",
     "Network-layer filtering and intrusion detection for connected devices."),

    # --- analytics ---
    ("PROD-026", "Business Intelligence Suite", 3, 20.00, "PROD-006,PROD-011", "analytics",
     "Self-service BI with data modeling, live dashboards, and scheduled refresh."),
    ("PROD-027", "Customer Insights Add-on", 3, 15.00, "PROD-006,PROD-026", "analytics",
     "Unifies customer data sources into a single profile for segmentation."),
    ("PROD-028", "Data Warehouse Connector Pack", 2, 9.50, "PROD-026", "analytics",
     "Prebuilt connectors for syncing usage data into external data warehouses."),
    ("PROD-029", "Predictive Analytics Add-on", 3, 18.00, "PROD-011,PROD-026", "analytics",
     "Forecasting models for usage, churn, and revenue trends."),
    ("PROD-030", "Real-Time Reporting Add-on", 2, 7.00, "PROD-006", "analytics",
     "Live operational dashboards refreshed on a sub-minute cadence."),

    # --- storage ---
    ("PROD-031", "Additional Storage Pack (5TB)", 1, 11.00, "PROD-001,PROD-002,PROD-003", "storage",
     "Large cloud storage expansion for media-heavy or archival-heavy accounts."),
    ("PROD-032", "Archive Mailbox Add-on", 2, 3.50, "PROD-008,PROD-031", "storage",
     "Long-term, low-cost mailbox archiving separate from primary storage."),
    ("PROD-033", "Cold Storage Tier Add-on", 1, 1.50, "PROD-008,PROD-031", "storage",
     "Lowest-cost storage tier for rarely-accessed backup and archival data."),
    ("PROD-034", "Cross-Region Replication Add-on", 3, 6.50, "PROD-012,PROD-031", "storage",
     "Replicates storage across regions for disaster-recovery requirements."),

    # --- communications ---
    ("PROD-035", "Contact Center Add-on", 3, 25.00, "PROD-009,PROD-004", "communications",
     "Omnichannel contact center with queueing, routing, and call analytics."),
    ("PROD-036", "SMS & Messaging Add-on", 1, 5.00, "PROD-009", "communications",
     "Two-way SMS and rich messaging integrated with the core communications stack."),
    ("PROD-037", "Video Conferencing Plus", 2, 7.50, "PROD-003,PROD-004", "communications",
     "Larger meeting sizes, webinar hosting, and meeting recording/transcription."),
    ("PROD-038", "Toll-Free Calling Add-on", 2, 6.00, "PROD-009,PROD-035", "communications",
     "Toll-free numbers and inbound minute bundles for the calling add-on."),
    ("PROD-039", "International Calling Plan", 2, 9.00, "PROD-009", "communications",
     "Bundled international minutes across 60+ destination countries."),

    # --- support ---
    ("PROD-040", "Enterprise Support Plan", 3, 9.00, "PROD-004,PROD-010", "support",
     "24/7 priority support with a named technical account manager."),
    ("PROD-041", "Onboarding & Migration Services", 1, 15.00, "PROD-010", "support",
     "One-time guided onboarding and data migration assistance package."),
    ("PROD-042", "Training & Adoption Add-on", 1, 3.50, "PROD-010,PROD-011", "support",
     "Guided training content and adoption tracking to drive feature usage."),
    ("PROD-043", "Health Check & Advisory Add-on", 2, 5.00, "PROD-010,PROD-040", "support",
     "Quarterly tenant health reviews and configuration recommendations."),

    # --- integration / platform ---
    ("PROD-044", "API & Developer Platform Add-on", 2, 10.00, "PROD-003,PROD-004", "integration",
     "Extended API rate limits and developer sandbox environments."),
    ("PROD-045", "Workflow Automation Add-on", 2, 8.50, "PROD-011,PROD-044", "integration",
     "Low-code workflow builder connecting apps, forms, and approvals."),
    ("PROD-046", "Third-Party App Connector Pack", 1, 4.00, "PROD-044", "integration",
     "Prebuilt connectors for popular CRM, ERP, and ticketing systems."),
    ("PROD-047", "Custom App Hosting Add-on", 3, 14.00, "PROD-044,PROD-045", "integration",
     "Hosts internally-built line-of-business apps with managed scaling."),

    # --- device management ---
    ("PROD-048", "Mobile Device Management Add-on", 2, 6.00, "PROD-003,PROD-004,PROD-005", "device-management",
     "Enrollment, policy enforcement, and remote wipe for mobile devices."),
    ("PROD-049", "Endpoint Analytics Add-on", 2, 5.50, "PROD-048,PROD-006", "device-management",
     "Startup performance, app reliability, and proactive remediation insights."),
    ("PROD-050", "Autopilot Device Provisioning", 1, 3.00, "PROD-048", "device-management",
     "Zero-touch provisioning for new devices shipped directly to end users."),
    ("PROD-051", "Kiosk & Shared Device Management", 1, 4.00, "PROD-048,PROD-015", "device-management",
     "Lockdown profiles and shared-device sign-in for kiosk and frontline hardware."),

    # --- AI / productivity ---
    ("PROD-052", "AI Copilot for Sales", 3, 35.00, "PROD-011,PROD-027", "analytics",
     "AI-generated deal summaries, next-best-action prompts, and CRM sync."),
    ("PROD-053", "AI Copilot for Service", 3, 32.00, "PROD-011,PROD-010", "support",
     "AI-assisted case summarization and suggested resolutions for support agents."),
    ("PROD-054", "Meeting Intelligence Add-on", 2, 9.50, "PROD-037,PROD-011", "communications",
     "Automatic meeting notes, action items, and searchable transcripts."),
]


def seed(tenant_ids=("acme", "synthetic_clean")):
    """Seeds the same catalog for each tenant_id given -- product_catalog is
    tenant-scoped (PRIMARY KEY (tenant_id, product_id)), so each company
    gets its own copy of these rows even though the demo data is identical."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Create tables if this is a brand new/empty DB file -- avoids requiring
    # a separate "run db.init_db() first" step before this script works.
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='product_catalog'")
    if cur.fetchone() is None:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        print(f"No tables found in {DB_PATH} -- applied {schema_path} first.")

    for tenant_id in tenant_ids:
        cur.executemany(
            """INSERT INTO product_catalog
               (tenant_id, product_id, product_name, tier_level, price_per_seat, complements, category, description, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'demo_seed')
               ON CONFLICT(tenant_id, product_id) DO UPDATE SET
                 product_name = excluded.product_name,
                 tier_level = excluded.tier_level,
                 price_per_seat = excluded.price_per_seat,
                 complements = excluded.complements,
                 category = excluded.category,
                 description = excluded.description
                 -- deliberately does NOT touch `source` on conflict: if this
                 -- tenant_id/product_id pair already exists as a real
                 -- source='upload' row, re-running the demo seed must not
                 -- downgrade it back to 'demo_seed'.""",
            [(tenant_id, *row) for row in PRODUCTS],
        )
    conn.commit()
    conn.close()
    print(f"Seeded {len(PRODUCTS)} products into product_catalog for tenants: {list(tenant_ids)}.")
    # app/agents/workflow.py skips catalog retrieval (rule/keyword matching
    # only) below CATALOG_SIZE_FLOOR = 50 products -- there's no reasoning
    # value in vector-narrowing a dozen items. This seed set is intentionally
    # kept above that floor so the Azure multi-agent retrieval step actually
    # exercises find_similar_products() instead of always taking the
    # "skipped_small_catalog" path.
    if len(PRODUCTS) < 50:
        print(f"WARNING: only {len(PRODUCTS)} products -- below the 50-product "
              "floor in app/agents/workflow.py, so vector search / catalog "
              "retrieval will still be skipped.")
    print("Run `python3 -c \"from app.vector_engine import embed_and_store_catalog; "
          "from app import db; embed_and_store_catalog(db.get_product_catalog())\"` "
          "(or POST /catalog/embed) to enable vector search matching.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", action="append", dest="tenants",
                         help="tenant_id to seed (repeatable). Defaults to both demo tenants.")
    args = parser.parse_args()
    seed(tenant_ids=args.tenants or ("acme", "synthetic_clean"))
