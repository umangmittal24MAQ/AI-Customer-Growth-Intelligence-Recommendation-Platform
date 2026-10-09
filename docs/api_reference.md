# API Reference

Base URL: `http://localhost:5000/api`

All responses are JSON. CORS is enabled for the Vite dev server.

---

## `GET /customers`
List all customers with churn segment + opportunity summary.

**Response**
```json
[
  {
    "customer_id": 1,
    "company_name": "Acme Corp",
    "industry": "SaaS",
    "plan_tier": "Pro",
    "mrr": 1450.0,
    "region": "EMEA",
    "contract_renewal_date": "2026-05-01",
    "churn_score": 32.4,
    "churn_segment": "LOW",
    "total_opportunity": 19200.0,
    "recommendation_count": 3
  }
]
```

---

## `GET /customers/:id`
Full detail: customer, usage/support signals, churn breakdown, recommendations.

**Response**
```json
{
  "customer": { "customer_id": 1, "company_name": "Acme Corp", "...": "..." },
  "usage_signals": { "monthly_active_users": 120, "feature_adoption_pct": 82.0, "...": "..." },
  "support_signals": { "open_tickets": 1, "csat_score": 4.6, "nps_score": 70 },
  "churn": {
    "score": 32.4,
    "segment": "LOW",
    "factor_breakdown": { "usage": 4.5, "adoption": 3.6, "support": 2.0, "sentiment": 3.1, "recency": 1.5 },
    "explanation": "Churn score 32.4/100 (LOW)..."
  },
  "recommendations": [
    {
      "id": 12,
      "title": "Upsell — Enterprise Plan Upgrade",
      "type": "upsell",
      "revenue_opportunity": 14400.0,
      "confidence": 0.65,
      "justification": "Healthy account...",
      "escalation_flag": false,
      "status": "pending"
    }
  ]
}
```

---

## `POST /generate-recommendations`
Runs the 5-agent pipeline. Optional `?customer_id=<id>` to run for one customer;
omit to run for all.

**Response**
```json
{
  "processed": 70,
  "results": [
    { "customer_id": 1, "segment": "LOW", "churn_score": 32.4, "recommendation_count": 3 }
  ]
}
```

---

## `GET /recommendations/:customer_id`
Fetch stored recommendations for a customer, ranked by expected value.

---

## `GET /analytics/summary`
Churn distribution, total revenue opportunity, top recommendation types, top
customers, and the conversion funnel.

**Response**
```json
{
  "churn_distribution": [ { "segment": "HIGH", "count": 15 } ],
  "total_revenue_opportunity": 812400.0,
  "top_recommendation_types": [ { "type": "cross_sell", "count": 40, "revenue": 210000.0 } ],
  "top_customers": [ { "customer_id": 3, "company_name": "Globex", "segment": "LOW", "opportunity": 42000.0 } ],
  "conversion_funnel": [ { "segment": "LOW", "status": "accepted", "count": 5 } ]
}
```

---

## `POST /recommendations/:id/feedback`
Mark a recommendation accepted/rejected.

**Request**
```json
{ "status": "accepted" }
```
`status` ∈ `pending | accepted | rejected`.

**Response**
```json
{ "id": 12, "status": "accepted" }
```
