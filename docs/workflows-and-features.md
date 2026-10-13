# Traject workflows and features

Traject turns tenant-specific customer, usage, support, and product data into
evidence-grounded revenue recommendations. It supports unfamiliar datasets by
discovering column meaning at ingestion time instead of requiring fixed header
names.

## Main features

| Area | Feature | Behavior |
|---|---|---|
| Tenant access | Email/password authentication | Passwords are salted and hashed. Successful login issues a tenant-scoped API key used by later requests. |
| Isolation | Tenant-scoped reads and writes | Protected endpoints derive the tenant from validated `X-Tenant-Id` and `X-API-Key` headers. |
| Data ingestion | Schema-free CSV and Excel ingestion | The system infers labels, types, semantic roles, join keys, and a small set of concepts required for deterministic calculations. |
| Data quality | Prompt compilation and bounded self-correction | A tenant-specific prompt specification is compiled and tested against sample accounts. Unresolved concepts are recorded as schema gaps. |
| Revenue analysis | Deterministic screening | High churn, missing evidence, and accounts without credible expansion signals are stopped before model calls. |
| Product selection | Catalog eligibility | Only compatible upgrade and cross-sell candidates are sent to the recommendation agent. |
| AI reasoning | Recommendation agent | IndiaAI Qwen produces one grounded recommendation or abstains. Structured output is validated with Pydantic. |
| Independent review | Critic agent | A separate prompt reviews the proposed product against raw evidence and can veto it or reduce confidence. |
| Trust controls | Fail-closed behavior | Provider failures, invalid products, unsupported output, and critic vetoes cannot become approved recommendations. |
| Commercial output | Deal value | Recurring products use annualized value. Same-category upgrades use the incremental price; cross-sells use the full price. |
| User experience | Dashboard and customer analysis | Users can inspect customers, health signals, recommendations, confidence, rationale, and decision traces. |
| Follow-up | Chat, email, meetings, and feedback | Tenant-scoped chat and optional communication integrations support action after analysis. Feedback can recalibrate tenant scoring. |

## Tenant onboarding workflow

1. A user signs up with company name, email, password, and an optional demo preset.
2. Traject creates a unique tenant and a tenant-scoped API key.
3. A demo preset generates synthetic files, or CSV/XLSX files are placed in the
   tenant upload directory.
4. Login starts background ingestion for files that are new or changed.
5. Schema Discovery examines names, values, statistics, and sample rows.
6. Deterministic validation removes structurally invalid mappings, such as a
   transaction value mapped as a catalog price.
7. Prompt Architect compiles tenant-specific reasoning instructions.
8. Self-correction checks sample accounts and records unresolved data gaps.
9. The dashboard exposes data status and enables analysis when customers and a
   product catalog are available.

## Recommendation workflow

1. Load one account or a batch of accounts within the authenticated tenant.
2. Normalize discovered columns into the small deterministic interface used for
   usage trend, adoption, tickets, renewal timing, and catalog calculations.
3. Apply the prefilter and deterministic risk screen.
4. Return a retention action when risk is high, evidence is missing, or no
   expansion signal exists.
5. Filter the tenant catalog to compatible candidates.
6. Ask the Recommendation agent to select at most one candidate and cite actual
   account evidence.
7. Reject products outside the eligible candidate set.
8. Ask the Critic agent to independently approve or veto the proposed product.
9. Reapply deterministic churn risk, calculate confidence and deal value, and
   store the result with an agent trace.
10. Return approved recommendations and transparent abstention reasons to the UI.

## Failure behavior

- Missing or malformed model output is retried within a bounded policy.
- A model fallback never manufactures an approved revenue lead.
- An invalid catalog product is removed.
- A critic failure or veto leaves the account in review rather than approving it.
- Missing usage concepts remain visible as data gaps instead of fabricated values.
- Recommendation scores and confidence values are constrained to their valid ranges.

## User-facing pages

- **Dashboard:** tenant summary, revenue opportunity, churn distribution, and recent recommendations.
- **Customers:** searchable account list with health and opportunity indicators.
- **Customer detail:** evidence, trend breakdown, recommendation, confidence, and actions.
- **Chat:** tenant-scoped conversational access to stored customer and recommendation data.
- **Settings:** catalog management, feature weights, and tenant configuration.

## Related documents

- [Architecture](architecture.md)
- [Data flow](data-flow.md)
- [API reference](api_reference.md)
- [Churn scoring](churn_scoring_logic.md)
