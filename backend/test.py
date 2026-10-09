import json
from app.db import get_latest_recommendations

TENANT_ID = "decathlon"  # change if your tenant id is different

recs = get_latest_recommendations(TENANT_ID)
print(f"Found {len(recs)} recommendations for tenant '{TENANT_ID}'\n")

for rec in recs[:3]:  # just check the first few
    print("=" * 60)
    print("customer_id:", rec.get("customer_id"))
    trace = rec.get("agent_trace")
    if isinstance(trace, str):
        trace = json.loads(trace) if trace else None
    print(json.dumps(trace, indent=2))