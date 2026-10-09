# Claude Code Prompt — Upsell Recommendation Agent (Full-Stack Build)

Copy everything below into Claude Code as your project instruction.

---

## PROJECT OVERVIEW

Build a full-stack **Upsell Recommendation Agent** for a Sales/Customer Success team. The system ingests customer data (usage, purchase history, support interactions), calculates a **churn risk score** per customer, segments them into **High / Medium / Low churn risk**, and generates **different recommendation strategies per segment**:

- **High churn risk** → Retention-focused plans (discounts, save offers, loyalty perks, executive escalation flag) — NOT upsell.
- **Medium churn risk** → Balanced recommendations (right-sizing plans, targeted feature adoption nudges, light cross-sell).
- **Low churn risk** → Aggressive upsell/cross-sell (premium plan upgrades, complementary products, contract renewal upgrades, personalized high-value offers).

All data for this build is **synthetic** — generate a realistic fake dataset for 50–100 companies at project start; no real customer data or external APIs needed.

---

## TECH STACK

**Backend**
- Python 3.11+, Flask (REST API)
- MAF (Multi-Agent Framework) for agent orchestration — structure the logic as a sequential multi-agent pipeline, not a single monolithic function
- SQLite for storage (simple, file-based — easy to demo/reset)
- Pydantic for data validation/schemas

**Frontend**
- React (Vite)
- Tailwind CSS
- Recharts or Chart.js for visualizations (churn distribution, revenue opportunity charts)
- Axios for API calls

**Other**
- python-dotenv for config
- Faker (Python library) for synthetic data generation

---

## AGENT PIPELINE (MAF Orchestration)

Build this as **5 sequential agents**, each with a single clear responsibility. Output of one agent feeds the next.

### 1. Signal Collection Agent
- Pulls raw customer signals: product usage frequency, feature adoption %, support ticket count/sentiment, contract renewal date, payment history, NPS/CSAT score (all synthetic).
- Normalizes into a single `CustomerSignal` object per customer.

### 2. Churn Risk Scoring Agent
- Computes a churn risk score (0–100) using weighted rules on the signals (e.g., low usage + high ticket volume + low NPS = high churn risk).
- Buckets into `HIGH` (score ≥ 70), `MEDIUM` (40–69), `LOW` (< 40).
- This score gates everything downstream — document the exact rule/weights in code comments so it's explainable, not a black box.

### 3. Catalog Retrieval Agent
- Given the customer's current plan/products, retrieves eligible catalog items (higher-tier plans, add-ons, complementary products) from the synthetic product catalog.
- Filters catalog based on churn segment (e.g., HIGH segment should never surface upgrade-only items — only retention/downgrade-safe or discount-eligible items).

### 4. Recommendation Generation Agent
- Generates the actual recommendation text + type, branching by segment:
  - **HIGH** → retention plan, discount %, escalation flag for CSM, reasoning ("why this customer is at risk")
  - **MEDIUM** → 1–2 targeted recommendations (feature adoption nudge or moderate cross-sell), reasoning
  - **LOW** → 2–3 upsell/cross-sell offers ranked by fit, reasoning
- Every recommendation must include a short human-readable justification string.

### 5. Revenue Opportunity Scoring Agent
- Assigns a $ opportunity value and confidence score to each recommendation.
- Produces a final ranked list per customer: `{recommendation, type, revenue_opportunity, confidence, justification}`.

**Deterministic fallback:** If the LLM call fails or times out at any agent step, fall back to a zero-cost rule-based version (simple if/else on churn score + plan tier) so the pipeline never breaks in a demo.

---

## SYNTHETIC DATA SPEC

Generate and seed a SQLite DB with:

**`customers` table**
- customer_id, company_name (Faker), industry, plan_tier (Starter/Pro/Enterprise), contract_start_date, contract_renewal_date, mrr (monthly recurring revenue), region

**`usage_signals` table**
- customer_id, monthly_active_users, feature_adoption_pct, login_frequency_per_week, last_login_date

**`support_signals` table**
- customer_id, open_tickets, avg_resolution_time_days, csat_score (1–5), nps_score (-100 to 100)

**`product_catalog` table**
- product_id, name, tier, price, category (add-on/upgrade/complementary), compatible_with_plan_tier

Generate at least 60 synthetic companies with realistic variance so all 3 churn segments are populated (roughly 20% high, 40% medium, 40% low).

---

## BACKEND API ENDPOINTS

- `GET /api/customers` — list all customers with churn segment + summary
- `GET /api/customers/:id` — full detail: signals, churn score breakdown, recommendations
- `POST /api/generate-recommendations` — triggers the 5-agent pipeline for all customers (or a single customer via `?customer_id=`)
- `GET /api/recommendations/:customer_id` — fetch stored recommendations
- `GET /api/analytics/summary` — churn segment distribution, total revenue opportunity, top recommendation types
- `POST /api/recommendations/:id/feedback` — mark a recommendation as accepted/rejected (for tracking conversion, per requirement below)

---

## FRONTEND REQUIREMENTS

1. **Dashboard (home)**: churn segment distribution chart, total revenue opportunity, top customers by opportunity
2. **Customer list view**: table with churn badge (red/yellow/green), plan tier, MRR, filter/sort by churn segment
3. **Customer detail view**: signals breakdown, churn score explanation, ranked recommendations with justification and $ value, accept/reject buttons
4. **Recommendations tracking view**: conversion funnel — recommended vs accepted vs rejected, by segment

Use Tailwind for a clean, modern SaaS-dashboard look — card-based layout, color-coded churn badges (red = high, amber = medium, green = low).

---

## ACCEPTANCE CRITERIA

- [ ] Synthetic data generator produces realistic, varied data across all churn segments
- [ ] Churn scoring logic is transparent and rule-documented (not just an LLM black box)
- [ ] High-churn customers ONLY ever receive retention offers, never pure upsell
- [ ] Medium and Low segments produce clearly differentiated recommendation types
- [ ] Every recommendation has a revenue opportunity value + confidence + justification
- [ ] Pipeline has a working zero-cost rule-based fallback if LLM/agent call fails
- [ ] Full pipeline runs end-to-end via one API call and reflects in the frontend
- [ ] Recommendations can be marked accepted/rejected and this is reflected in an analytics view

---

## SUGGESTED FOLDER STRUCTURE

```
upsell-recommendation-agent/
├── backend/
│   ├── app.py
│   ├── agents/
│   │   ├── signal_agent.py
│   │   ├── churn_scoring_agent.py
│   │   ├── catalog_retrieval_agent.py
│   │   ├── recommendation_agent.py
│   │   └── revenue_scoring_agent.py
│   ├── data/
│   │   ├── generate_synthetic_data.py
│   │   └── seed.db
│   ├── models/
│   │   └── schemas.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── api/
│   ├── tailwind.config.js
│   └── package.json
└── README.md
```

---

Build this step by step: first the synthetic data generator, then the 5-agent backend pipeline (test each agent independently), then the Flask API, then the React frontend. Confirm each layer works before moving to the next.
