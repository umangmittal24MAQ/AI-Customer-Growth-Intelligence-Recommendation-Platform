# Traject data flow

## End-to-end data flow diagram

```mermaid
flowchart TD
    A[User signs up or logs in] --> B[Issue tenant-scoped API key]
    B --> C{Tenant files available?}
    C -- No --> C1[Show empty-account data status]
    C -- Yes --> D[Read CSV or XLSX]

    D --> E[Compute column statistics and samples]
    E --> F[Schema Discovery with IndiaAI]
    F --> G[Validate concepts and join key]
    G --> H[Store dataset metadata, schema, and raw JSON rows]
    H --> I[Compile tenant prompt specification]
    I --> J[Run bounded sample self-correction]
    J --> K[Record resolved mappings and remaining gaps]

    K --> L[User requests customer or batch analysis]
    L --> M[Authenticate tenant headers]
    M --> N[Load tenant customer, usage, tickets, catalog, and dynamic fields]
    N --> O[Normalize deterministic concepts]
    O --> P{Risk and evidence screen}

    P -- High risk / weak evidence --> Q[Abstain and produce retention action]
    P -- Eligible --> R[Filter compatible catalog candidates]
    R --> S{Candidates found?}
    S -- No --> Q
    S -- Yes --> T[Recommendation agent]
    T --> U{Output and product valid?}
    U -- No --> Q
    U -- Yes --> V[Independent Critic agent]
    V --> W{Critic approves?}
    W -- No --> Q
    W -- Yes --> X[Calculate deterministic churn, confidence, and deal value]

    Q --> Y[Build decision trace]
    X --> Y
    Y --> Z[(Store recommendation and trace)]
    Z --> AA[FastAPI response]
    AA --> AB[Dashboard, customer detail, chat, or follow-up action]
```

## Ingestion transformations

| Input | Transformation | Stored result |
|---|---|---|
| File name and headers | Used as hints, never as the only evidence | Dataset label and exact source column names |
| Column values and statistics | Type, role, relevance, and meaning inference | Schema catalog entries |
| Customer/account identifier | Join-key validation | `entity_id` used across tenant datasets |
| Usage time series | Primary trend metric selection | Comparable trend rows for deterministic calculations |
| Support records | Severity, time, resolution, category, and subject concepts | Normalized ticket evidence plus raw fields |
| Product catalog | Product identity, name, tier, category, price, and description | Eligible products and deal-value inputs |
| Unrecognized columns | Preserved without forcing a concept | Dynamic fields available to agents and insights |

## Recommendation data contract

The model receives compact normalized signals, relevant raw schema-free rows, and
only the eligible product candidates. The final record contains:

- customer and renewal identifiers from stored source data;
- deterministic churn risk and reason;
- an approved catalog product or an explicit abstention reason;
- recommendation type, evidence-grounded rationale, and revenue score;
- confidence based on model confidence, data completeness, retrieval fit, and
  critic penalty;
- incremental upgrade or full cross-sell deal value;
- an agent trace showing gates, candidates, critic verdict, and fallbacks.

## Tenant and trust boundaries

```mermaid
sequenceDiagram
    participant UI as React UI
    participant API as FastAPI
    participant Auth as Tenant auth
    participant DB as SQLite
    participant AI as IndiaAI Qwen

    UI->>API: Request + tenant ID + API key
    API->>Auth: Verify header pair
    Auth->>DB: Read salted API-key hash
    DB-->>Auth: Tenant key record
    Auth-->>API: Verified tenant ID
    API->>DB: Tenant-scoped query
    DB-->>API: Tenant data only
    API->>AI: Compact evidence and eligible candidates
    AI-->>API: Structured response
    API->>API: Validate, gate, and critic-check
    API->>DB: Store tenant-scoped result and trace
    API-->>UI: Recommendation or abstention
```

Raw API keys and passwords are not stored in plaintext. Tenant uploads, runtime
databases, logs, and `.env` files are excluded from Git.
