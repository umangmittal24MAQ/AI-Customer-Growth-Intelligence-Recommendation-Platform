"""Create *synthetic* Traject SaaS demo datasets with deterministic challenge cases.

Usage: python -m scripts.generate_trust_demo
The 12-account showcase is also copied to data/tenant_uploads/traject-showcase.
"""
from __future__ import annotations
import csv
from datetime import date, timedelta
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / 'demo_data'
IN_APP = ROOT / 'backend' / 'data' / 'tenant_uploads' / 'traject-showcase'

PRODUCTS = [
    ('TRJ-CORE-1', 'Launch', 1, 14, 'core-plan'),
    ('TRJ-CORE-2', 'Growth', 2, 29, 'core-plan'),
    ('TRJ-CORE-3', 'Scale', 3, 58, 'core-plan'),
    ('TRJ-CORE-4', 'Enterprise', 4, 95, 'core-plan'),
    ('TRJ-SEC-1', 'Security Compliance Suite', 2, 11, 'security'),
    ('TRJ-ANA-1', 'Usage Analytics Add-on', 2, 8, 'analytics'),
    ('TRJ-API-1', 'API Automation Pack', 2, 7, 'automation'),
    ('TRJ-STO-1', 'Extra Cloud Storage', 1, 5, 'storage'),
    ('TRJ-ADV-1', 'Priority Support', 2, 9, 'support'),
    ('TRJ-OTHER-1', 'Tennis Coaching Plan', 3, 48, 'sports'),
    ('TRJ-OTHER-2', 'Retail POS Terminal', 3, 39, 'hardware'),
    ('TRJ-OTHER-3', 'Medical Claims System', 4, 52, 'healthcare'),
]

# Two demo modes: quickly run 12 accounts or a more realistic 36-account portfolio.
SCENARIOS = [
    ('Northstar Data Labs', 'Launch', 'strong_growth', 'Up to Growth', 'Usage and seats growing'),
    ('Atlas Cloudworks', 'Growth', 'strong_growth', 'Up to Scale', 'Monthly usage climbing'),
    ('BluePeak Analytics', 'Launch', 'strong_growth', 'Up to Growth', 'Growing usage'),
    ('Monarch Automation', 'Growth', 'strong_growth', 'Up to Scale', 'API traffic expanding'),
    ('Meridian Software', 'Scale', 'strong_growth', 'Up to Enterprise', 'High engagement'),
    ('Clearview Technologies', 'Launch', 'strong_growth', 'Up to Growth', 'Fast team growth'),
    ('Vela Infrastructure', 'Growth', 'support_risk', 'Hold and retain', 'Unresolved billing dispute near renewal'),
    ('Summit Retail Systems', 'Growth', 'declining', 'Hold and retain', 'Declining feature adoption'),
    ('Orbit Digital', 'Scale', 'declining', 'Hold and retain', 'Engagement drop'),
    ('Cedarline Platforms', 'Growth', 'thin_evidence', 'Request more data', 'Missing usage history'),
    ('Pioneer Tech Studio', 'Scale', 'steady', 'No strong opportunity', 'Flat usage, renewal far away'),
    ('Harborstone Apps', 'Launch', 'steady', 'No strong opportunity', 'Flat usage, renewal far away'),
    ('Lattice Data Systems', 'Launch', 'strong_growth', 'Up to Growth', 'High activity growth'),
    ('Quanta Stack', 'Growth', 'strong_growth', 'Up to Scale', 'Large API expansion'),
    ('Vertex Operations', 'Scale', 'strong_growth', 'Up to Enterprise', 'Consistent utilization'),
    ('Nexa Compute', 'Launch', 'strong_growth', 'Up to Growth', 'Growing organization'),
    ('SignalBridge', 'Growth', 'strong_growth', 'Up to Scale', 'Feature adoption up'),
    ('Brightline AI', 'Growth', 'strong_growth', 'Up to Scale', 'Active seats increasing'),
    ('Ember Security', 'Growth', 'support_risk', 'Hold and retain', 'Security escalation unresolved'),
    ('Horizon Code', 'Growth', 'declining', 'Hold and retain', 'Loss of engagement'),
    ('NovaScale Software', 'Launch', 'thin_evidence', 'Request more data', 'Usage data missing'),
    ('Kiteworks Labs', 'Enterprise', 'steady', 'No strong opportunity', 'Highest plan, stable'),
    ('Acorn Digital', 'Growth', 'steady', 'No strong opportunity', 'Stable account'),
    ('Ardent Cloud', 'Launch', 'steady', 'No strong opportunity', 'Stable with distant renewal'),
    ('UnionLake AI', 'Launch', 'strong_growth', 'Up to Growth', 'Rapid growth'),
    ('FluxWare', 'Growth', 'strong_growth', 'Up to Scale', 'API increase'),
    ('OriginFlow Tech', 'Scale', 'strong_growth', 'Up to Enterprise', 'Growth and renew soon'),
    ('Highland Systems', 'Launch', 'strong_growth', 'Up to Growth', 'Adoption growth'),
    ('Anchorpoint', 'Growth', 'declining', 'Hold and retain', 'Adoption declined'),
    ('Shoreline Cloud', 'Growth', 'support_risk', 'Hold and retain', 'Renewal and billing dispute'),
    ('Marble Networks', 'Enterprise', 'steady', 'No strong opportunity', 'No eligible core upgrade'),
    ('Sagebyte Products', 'Growth', 'thin_evidence', 'Request more data', 'No recent usage samples'),
    ('Boreal Data', 'Scale', 'strong_growth', 'Up to Enterprise', 'Engagement accelerating'),
    ('Prism Applications', 'Growth', 'steady', 'No strong opportunity', 'No action trigger'),
    ('Eclipse Cloud', 'Launch', 'strong_growth', 'Up to Growth', 'Growing usage'),
    ('TwinPeak Systems', 'Growth', 'declining', 'Hold and retain', 'Severe usage decay'),
]


def write_csv(path, fieldnames, rows):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_dataset(size: int, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    today = date(2026, 10, 9)
    customer_rows, usage_rows, ticket_rows, labels = [], [], [], []
    for idx, (name, plan, kind, expectation, why) in enumerate(SCENARIOS[:size], 1):
        cid = f'DEMO-{idx:03d}'
        seats = 15 + idx * 3
        nps = -35 if kind == 'support_risk' else 15 if kind == 'declining' else 68 if kind == 'strong_growth' else 45
        renewal = today + timedelta(days=25 if kind == 'support_risk' else 85 if kind == 'strong_growth' else 230)
        customer_rows.append(dict(workspace_id=cid, customer_org=name, subscription_tier=plan,
                                  licensed_seats=seats, renews_on=renewal.isoformat(),
                                  csm_owner=f'Account manager {idx%5+1}', nps_last_survey=nps))
        if kind != 'thin_evidence':
            vals = ([30, 46, 65, 91] if kind == 'strong_growth' else
                    [92, 71, 52, 29] if kind == 'declining' else
                    [76, 73, 66, 55] if kind == 'support_risk' else [55, 56, 55, 56])
            for n, score in enumerate(vals):
                month = date(2026, 6 + n, 9)
                usage_rows.append(dict(workspace_id=cid, usage_month=month.isoformat(),
                                       product_engagement_index=score, monthly_active_devs=int(seats*score/100),
                                       data_stored_gb=round(55+score*3.2, 1), storage_plan_cap_gb=500,
                                       api_calls=score*7000+idx*390))
        if kind == 'support_risk':
            ticket_rows.append(dict(workspace_id=cid, issue_category='billing',
                        summary='URGENT: contract billing dispute and cancellation request not resolved',
                        opened_on='2026-10-03', is_closed='False'))
        elif kind == 'strong_growth' and idx % 3 == 0:
            ticket_rows.append(dict(workspace_id=cid, issue_category='onboarding',
                        summary='Customer asks about additional seats and higher-tier capacity',
                        opened_on='2026-09-29', is_closed='True'))
        labels.append(dict(customer_id=cid, customer_name=name, scenario=kind,
                           reviewer_expected_action=expectation, reviewer_reason=why))
    write_csv(dest/'subscriptions.csv', list(customer_rows[0]), customer_rows)
    write_csv(dest/'product_usage.csv', ['workspace_id','usage_month','product_engagement_index',
        'monthly_active_devs','data_stored_gb','storage_plan_cap_gb','api_calls'], usage_rows)
    write_csv(dest/'support_issues.csv', ['workspace_id','issue_category','summary','opened_on','is_closed'], ticket_rows)
    write_csv(dest/'product_catalog.csv', ['sku','offering_name','tier','seat_price_usd','product_group'],
        [dict(zip(['sku','offering_name','tier','seat_price_usd','product_group'], p)) for p in PRODUCTS])
    write_csv(dest/'reviewer_labels_DO_NOT_UPLOAD.csv', list(labels[0]), labels)
    return len(customer_rows)


def main():
    small = DEMO/'showcase_12_accounts'; large = DEMO/'benchmark_36_accounts'
    make_dataset(12, small)
    make_dataset(36, large)
    IN_APP.mkdir(parents=True, exist_ok=True)
    for file in small.glob('*.csv'):
        if not file.name.startswith('reviewer_'):
            shutil.copy2(file, IN_APP/file.name)
    print('Synthetic datasets prepared:', small, large)
    print('Ready-to-login tenant: traject-showcase (12 accounts, 12 products)')

if __name__ == '__main__':
    main()
