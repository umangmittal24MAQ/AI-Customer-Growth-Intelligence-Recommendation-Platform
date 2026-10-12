# Traject architecture (October 2026)

## Runtime boundaries

| Layer | Primary files | Responsibility |
|---|---|---|
| UI | `frontend/src/pages`, `frontend/src/components` | Dashboard, customer analysis, opportunity tracking, chat |
| API | `backend/app/main.py`, `backend/app/web_api.py` | FastAPI HTTP routing, Pydantic contracts, tenant authorization |
| Identity | `backend/app/accounts.py`, `backend/app/auth.py` | Password verification and tenant-scoped API keys |
| Ingestion | `backend/scripts/run_tenant_ingestion.py`, `backend/app/schema_*`, `backend/app/data_ingestion.py` | Tenant CSV discovery, column mapping, normalized records |
| Decisions | `backend/app/pipeline.py`, `backend/app/prefilter.py`, `backend/app/trust.py` | Prefilter, compatible catalog retrieval, deterministic vetoes and abstention |
| Agents | `backend/app/agents/workflow.py`, `backend/app/agents/clients.py` | Recommendation and independent Critic with validated structured outputs |
| Model gateway | `backend/app/indiaai_client.py`, `backend/app/llm_retry.py` | IndiaAI Qwen-only OpenAI-compatible client and bounded retries |
| Storage | `backend/app/db.py`, `backend/data/schema.sql` | SQLite tenant-scoped persistence |

## Decision pipeline

1. Authenticate caller from `X-Tenant-Id` and `X-API-Key` headers.
2. Read only the tenant's accounts, support signals, usage and eligible catalog products.
3. Deterministically screen evidence and risk before spending model tokens.
4. Ask Qwen for an evidence-constrained recommendation; validate JSON with Pydantic.
5. Give raw evidence and the proposed product to a separate Critic prompt.
6. Enforce eligibility, Critic veto, evidence gates and fail-closed fallback behavior.
7. Store outcome and trace for the dashboard.

The Recommendation and Critic are *separate agent instructions*, not different models. Both share one client connection pool against the configured Qwen deployment; the Critic has an independent prompt and a distinct judgement. Failures safely yield no approved upsell.

## Project organization and local startup

- `backend/app`: API, domain logic, model adapter, and persistence. The large `db.py`, `chat_agent.py`, and `web_api.py` remain cohesive legacy modules; future domain-specific extraction should be performed incrementally with regression tests.
- `backend/scripts`: ingestion, data-generation and diagnostic CLIs.
- `backend/tests`: backend contract and trust-gate tests; network calls are mocked except explicitly opt-in live tests.
- `demo_data`: curated synthetic 12-account showcase and 36-account benchmark.
- `backend/data/tenant_uploads`: runtime tenant inputs and historical demo fixtures. New files are gitignored because real uploads must never be committed.
- `frontend/src/api`: browser's tenant-scoped API client.

See the root README for commands; GitHub Actions runs backend tests and frontend build on pushes and pull requests.

## Known production-hardening work (not claimed complete)

- Replace the SQLite/thread-based local ingest jobs with a queue and stronger transactional/idempotency guarantees for scale.
- Split large HTTP handlers and persistence methods into domain modules once integration test coverage is expanded.
- Replace browser `sessionStorage` API-key auth with robust server-managed sessions, expirations and CSRF protections for production.
- Require secure per-deployment `API_KEY_SALT`, HTTPS, deployment-specific CORS, and authorization before the private model gateway is used.
- Review all legacy tenant fixture CSVs before any public release. Do not ingest customer or corporate confidential records.
- Benchmark live gateway latency, JSON success rate, failure recovery and human-labeled quality.
