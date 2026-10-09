# Traject API Reference

**Local server:** `http://127.0.0.1:5001` (or your configured host/port). Interactive endpoint schemas: [Swagger UI](http://127.0.0.1:5001/docs).

The React frontend uses `/api/*`; these routes generally require the tenant authentication credential returned by `POST /auth/login`. Use the OpenAPI documentation to check the exact request body and auth header for your version.

## Authentication

| Method | Route | Purpose |
|---|---|---|
| POST | `/auth/signup` | Create a tenant account; can initialize showcase data |
| POST | `/auth/login` | Sign in and receive tenant-scoped credentials |

## Frontend-facing endpoints

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/data-status` | Ingested data counts and gaps |
| GET | `/api/catalog` | Tenant-scoped catalog |
| GET | `/api/customers` | Customer list |
| GET | `/api/customers/{customer_id}` | Customer detail |
| GET | `/api/customers/{customer_id}/analysis` | Customer analytics, reasoning and insights |
| POST | `/api/generate-recommendations` | Analyze all accounts, or provide `customer_id` query parameter for one |
| GET | `/api/recommendations/{customer_id}` | Recommendation details |
| POST | `/api/recommendations/{rec_id}/feedback` | Record feedback |
| GET | `/api/analytics/summary` | Aggregate tenant analytics |
| POST | `/api/chat` | Chat with account context |
| GET | `/api/chat/sessions` | List chat sessions |
| GET | `/api/chat/sessions/{conversation_id}` | Chat session history |
| DELETE | `/api/chat/sessions/{conversation_id}` | Delete a chat session |
| POST | `/api/customers/{customer_id}/send-recommendation-email` | Send an opportunity email |
| POST | `/api/customers/{customer_id}/schedule-meeting` | Arrange a follow-up |
| POST | `/api/catalog/products` | Add catalog entry |
| PATCH | `/api/catalog/products/{product_id}` | Update catalog entry |
| DELETE | `/api/catalog/products/{product_id}` | Remove catalog entry |
| GET | `/api/tenant/feature-weights` | Inspect scoring feature weights |
| POST | `/api/tenant/feature-weights` | Update scoring feature weights |

Additional operations (batch email, tenant configuration, calibration, traces, embeddings) are available in `backend/app/main.py` and `backend/app/web_api.py`.

## Data and safety behavior

- Generate-recommendations requires tenant data and an **uploaded product catalog**; seeded placeholder catalogs are not sufficient.
- The pipeline may return **no recommendation** if evidence is missing, churn risk is high, model output is invalid, or the Critic vetoes a proposed product.
- Only the MAQ-hosted IndiaAI Qwen model is configured for AI inference; a deterministic, conservative fallback operates when unavailable.
- The full response contracts are maintained in the FastAPI Pydantic schemas and live OpenAPI spec rather than duplicated as static sample JSON here.
