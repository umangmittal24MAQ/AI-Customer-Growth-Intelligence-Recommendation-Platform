# Traject — Current Code Structure

This describes the **implemented** React + FastAPI application. The original early design notes are archived under `docs/legacy/` and should not be used as implementation instructions.

```text
Traject/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, auth, tenant APIs
│   │   ├── web_api.py              # Frontend-facing /api routes
│   │   ├── auth.py, accounts.py     # Tenant authentication and onboarding
│   │   ├── db.py, data_ingestion.py # SQLite persistence and CSV ingestion
│   │   ├── schema_discovery.py
│   │   ├── schema_mapping.py       # Flexible incoming CSV schema handling
│   │   ├── pipeline.py             # Shortlist, invoke agents, store results
│   │   ├── prefilter.py, trust.py   # Deterministic evidence and safety checks
│   │   ├── indiaai_client.py       # Sole LLM gateway, OpenAI-compatible SDK
│   │   ├── llm_retry.py            # Bounded transient-error retries
│   │   └── agents/
│   │       ├── workflow.py         # Recommendation + independent Critic
│   │       ├── clients.py          # Structured JSON outputs and safe fallbacks
│   │       ├── recommendation_agent.py
│   │       ├── critic_agent.py
│   │       └── ...                 # Supporting agent components
│   ├── data/
│   │   ├── schema.sql
│   │   └── tenant_uploads/         # Synthetic tenant CSV fixtures
│   ├── scripts/
│   │   ├── test_indiaai_connection.py
│   │   └── smoke_optimized_demo.py
│   ├── tests/
│   ├── requirements-core.txt       # Local demo dependencies
│   └── .env.example                # Safe configuration template
├── frontend/
│   ├── src/
│   │   ├── pages/                  # Dashboard, customers, tracking, chat
│   │   ├── components/
│   │   ├── api/
│   │   └── context/
│   └── package.json
├── demo_data/
│   ├── showcase_12_accounts/
│   └── benchmark_36_accounts/
└── docs/
    ├── api_reference.md
    ├── churn_scoring_logic.md
    └── legacy/                   # Archived original planning documents
```

## Execution flow

1. Tenant signs up and ingests CSV files, optionally using the synthetic showcase.
2. Schema discovery and normalization make customer, usage, ticket and product data available.
3. Deterministic prefilter shortlists accounts. Candidate-product screening prevents incompatible upsells.
4. The **IndiaAI-hosted Qwen** recommendation agent proposes a structured draft.
5. An independent Critic evaluates it; deterministic trust gates can veto or abstain.
6. Approved recommendations and retention outcomes are stored and shown in the dashboard.

**LLM provider:** IndiaAI Qwen only. `openai` is the compatible HTTP client library; it does not imply inference on OpenAI services. Runtime model credentials stay in `backend/.env` and must never be committed.

Run locally: see [README](../README.md) and [IndiaAI setup](../INDIAAI_SETUP.md).
