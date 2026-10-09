# Upsell Recommendation Agent — Detailed Project Structure

```
upsell-recommendation-agent/
│
├── backend/
│   ├── app.py                              # Flask app entry point, registers routes/blueprints
│   ├── config.py                           # Env config: DB path, LLM keys, churn thresholds
│   ├── requirements.txt                    # flask, pydantic, faker, python-dotenv, openai/azure-openai-sdk
│   ├── .env.example                        # Template for API keys / secrets
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── orchestrator.py                 # MAF pipeline runner — chains all 5 agents in sequence
│   │   ├── signal_agent.py                 # Agent 1: collects & normalizes raw customer signals
│   │   ├── churn_scoring_agent.py          # Agent 2: computes churn score + segment (HIGH/MED/LOW)
│   │   ├── catalog_retrieval_agent.py      # Agent 3: fetches eligible catalog items per segment
│   │   ├── recommendation_agent.py         # Agent 4: generates segment-specific recommendations
│   │   ├── revenue_scoring_agent.py        # Agent 5: assigns $ opportunity + confidence
│   │   └── fallback_rules.py               # Zero-cost rule-based fallback logic (no LLM call)
│   │
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── customers.py                    # GET /api/customers, GET /api/customers/:id
│   │   ├── recommendations.py              # POST /generate-recommendations, GET /recommendations/:id
│   │   ├── analytics.py                    # GET /api/analytics/summary
│   │   └── feedback.py                     # POST /api/recommendations/:id/feedback
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schemas.py                      # Pydantic models: CustomerSignal, ChurnScore, Recommendation
│   │   └── db_models.py                    # SQLite table definitions (SQLAlchemy or raw sqlite3)
│   │
│   ├── data/
│   │   ├── generate_synthetic_data.py      # Faker-based generator: 60+ companies, signals, catalog
│   │   ├── product_catalog_seed.py         # Static synthetic product/plan catalog
│   │   └── seed.db                         # Generated SQLite DB (created at runtime, gitignored)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── db_service.py                   # DB connection + query helpers
│   │   └── llm_service.py                  # Wraps Azure OpenAI / MAF client calls, retry + timeout logic
│   │
│   └── tests/
│       ├── test_churn_scoring.py           # Unit tests for churn score thresholds
│       ├── test_recommendation_agent.py    # Ensures HIGH segment never gets upsell-only output
│       └── test_pipeline_e2e.py            # End-to-end pipeline run on sample synthetic data
│
├── frontend/
│   ├── package.json
│   ├── tailwind.config.js
│   ├── vite.config.js
│   ├── index.html
│   │
│   ├── src/
│   │   ├── main.jsx                        # React entry point
│   │   ├── App.jsx                         # Router setup (Dashboard / CustomerList / CustomerDetail / Tracking)
│   │   │
│   │   ├── api/
│   │   │   └── client.js                   # Axios instance + API call functions
│   │   │
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx                # Home: churn distribution chart, top opportunities
│   │   │   ├── CustomerList.jsx             # Table view with churn badges, filters, sort
│   │   │   ├── CustomerDetail.jsx           # Signals, churn breakdown, recommendations, accept/reject
│   │   │   └── RecommendationsTracking.jsx  # Conversion funnel: recommended vs accepted vs rejected
│   │   │
│   │   ├── components/
│   │   │   ├── ChurnBadge.jsx               # Red/Amber/Green badge component
│   │   │   ├── RecommendationCard.jsx       # Single recommendation display + accept/reject buttons
│   │   │   ├── RevenueChart.jsx             # Recharts bar/line chart for opportunity value
│   │   │   ├── ChurnDistributionChart.jsx   # Pie/donut chart of HIGH/MED/LOW segment split
│   │   │   └── Navbar.jsx                   # Top navigation
│   │   │
│   │   └── styles/
│   │       └── index.css                   # Tailwind base imports
│   │
│   └── public/
│       └── favicon.ico
│
├── docs/
│   ├── PRD.md                              # Product requirements doc (already exists — link/copy in)
│   ├── churn_scoring_logic.md              # Documented weights/rules for churn score (explainability)
│   └── api_reference.md                    # Endpoint list with sample request/response payloads
│
├── .gitignore                              # node_modules, *.db, .env, __pycache__
└── README.md                               # Setup instructions: backend + frontend run steps
```

---

## Build Order (recommended sequence for Claude Code)

1. **`backend/data/generate_synthetic_data.py`** — get realistic data flowing first; verify segment distribution (~20% high, 40% medium, 40% low).
2. **`backend/models/schemas.py` + `db_models.py`** — lock down data shapes before writing agent logic.
3. **`backend/agents/*`** — build and unit-test each agent independently (especially `churn_scoring_agent.py` and `fallback_rules.py`) before chaining them in `orchestrator.py`.
4. **`backend/routes/*`** — expose the pipeline via Flask once agents are verified.
5. **`frontend/src/pages/*`** — build Dashboard first (fastest to validate data is flowing end-to-end), then CustomerList → CustomerDetail → Tracking.
6. **`docs/churn_scoring_logic.md`** — write this alongside step 3 so the scoring rule stays explainable, not buried in code.

---

## Notes on key files

- **`orchestrator.py`** is the heart of the MAF pipeline — it should be the only place that knows the agent execution order, so agents stay swappable/testable in isolation.
- **`fallback_rules.py`** must mirror the *segment behavior* of the LLM path (HIGH → retention only, etc.) even though it's simpler — this is what keeps demos safe if the LLM call fails.
- **`llm_service.py`** centralizes all Azure OpenAI/MAF calls so retry, timeout, and fallback-trigger logic lives in one place instead of being duplicated across 5 agents.
