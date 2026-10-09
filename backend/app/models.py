from pydantic import BaseModel
from typing import Optional, Literal   

class Product(BaseModel):              
    product_name: str
    price_per_seat: float
    description: Optional[str] = None


class Recommendation(BaseModel):
    id: Optional[int] = None
    customer_id: str
    customer_name: str
    segment: str
    churn_risk: str
    churn_reason: str
    recommended_product: Optional[str] = None
    recommendation_type: Optional[str] = None
    rationale: str
    revenue_score: float
    estimated_deal_value: float = 0
    renewal_date: str
    generated_at: str
    outcome: Optional[str] = None


class RunResponse(BaseModel):
    count: int
    recommendations: list[Recommendation]
    total_customers: int  # how many customers exist in the DB at all, regardless of shortlisting --
                           # lets the caller tell "no data uploaded yet" apart from "uploaded but 0 qualified"
    total_catalog_products: int


class OutcomeUpdate(BaseModel):
    outcome: str  # 'accepted' | 'rejected' | 'converted'


class RecommendationDraft(BaseModel):
    """
    The Recommendation Agent's actual LLM response contract, matching
    PRD §5 exactly. Deliberately slim -- the agent has no business knowing
    or inventing customer_id, customer_name, renewal_date, or generated_at;
    those get filled in from the real customer record in workflow.py after
    the agent runs. Using the full DB-shaped `Recommendation` model below as
    an LLM response_format would force the model to hallucinate fields like
    renewal_date/generated_at it has no reliable way to produce correctly.
    """
    product: Optional[str] = None
    segment: str
    churn_risk: Literal["low", "medium", "high"]
    churn_reason: str
    rationale: str
    revenue_score: float
    # How sure the agent is that this recommendation is RIGHT for this
    # customer, given the evidence actually present -- distinct from
    # revenue_score (which is potential upside). 0.0-1.0. Defaults to 0.5 so
    # a heuristic fallback (app/agents/clients.py) or an older prompt that
    # doesn't emit it still yields a valid draft. workflow._compute_confidence
    # blends this with data-completeness/retrieval-fit and applies penalties.
    confidence: float = 0.5


class RetentionAction(BaseModel):
    """
    The Retention Agent's response contract. Fires only for customers the
    pipeline decided NOT to pitch an upsell to (no_recommendation_reason_code
    is set) -- instead of leaving the rep with a static "hold offers" line,
    this proposes one concrete, specific next step for THIS account, grounded
    in its actual churn_reason/signals.
    """
    reason_summary: str  # this agent's own one-sentence "why no upsell" for THIS account, grounded in the signals given -- replaces the rule-engine's static churn_reason text everywhere this fires
    action_type: Literal[
        "executive_meeting", "complimentary_offer", "training_session",
        "account_review", "proactive_outreach", "monitor",
    ]
    action_text: str  # concrete, specific next step a rep can act on today
    talking_point: Optional[str] = None  # one grounded reason to open the conversation with


class SchemaGapFlag(BaseModel):
    """
    Same shape Stage 3's sample-check LLM call already produces (see
    app/schema_self_correction.py's _run_check) -- kept as a small parallel
    model rather than folded loosely into SignalVerdict's fields so it can
    be reused as-is wherever a flag needs to travel (Signal agent output,
    Stage-3 checks, future gap-reporting).
    """
    concept: Optional[str] = None
    flag_type: Literal["missing_concept", "low_confidence"]
    detail: str


class SignalVerdict(BaseModel):
    proceed: bool
    reason: str
    urgency: Literal["low", "medium", "high"]
    # Added for Stage 4 (schema-free payloads): lets the *production*
    # Signal agent raise the same missing_concept/low_confidence flags
    # Stage 3 only ever produced at ingestion-time, against a live
    # customer's actual generic `datasets` payload. Defaults to an empty
    # list so existing callers/tests built against the old 3-field
    # SignalVerdict (proceed/reason/urgency) keep working unmodified.
    flags: list["SchemaGapFlag"] = []

class CandidateProducts(BaseModel):
    products: list[Product]
    # How the candidate list was produced, for the agent trace:
    #   keyword               - keyword match (rule engine path)
    #   vector                - semantic vector search matched products
    #   skipped_small_catalog - catalog below the size floor, used as-is
    #   full_catalog_fallback - vector search had no embeddings, used full catalog
    method_used: Literal["keyword", "vector", "skipped_small_catalog", "full_catalog_fallback"]

class CriticVerdict(BaseModel):
    approved: bool
    revised_churn_risk: Literal["low", "medium", "high"] | None
    # Why the *product recommendation* is being rejected/kept -- may name
    # the proposed product. Only ever shown alongside that same proposed
    # product (agent trace / logs) -- never as the customer-facing churn
    # explanation, since a fallback pitch can later swap in a different
    # product this text was never about. See churn_risk_reason below.
    veto_reason: str | None
    # Why the churn-risk LEVEL is what it is, in evidence terms only
    # (usage trend, tickets, renewal, dynamic fields, etc.) -- must NOT
    # reference the proposed product, so it stays valid even if the final
    # recommended product changes downstream (critic veto -> fallback
    # pitch). This is what the UI's churn explanation is built from.
    churn_risk_reason: str | None = None
    # Optional 0.0-1.0 fraction the critic can set to pull the final
    # confidence DOWN even when it approves the product -- e.g. "the product
    # is fine but the evidence is thinner than the recommendation implies."
    # None/0 leaves confidence untouched. Applied in
    # app/agents/confidence.compute_confidence as base *= (1 - penalty).
    confidence_penalty: float | None = None

class DealValue(BaseModel):
    estimated_value: float
    anomaly_flag: bool
    anomaly_reason: str | None


class InsightMetric(BaseModel):
    """One label/value/unit tuple inside an Insight.metrics list -- generic
    enough for the frontend to render without knowing the insight's
    category ahead of time (see Stage 6: InsightCard renders these as
    plain tuples, not category-specific fields)."""
    label: str
    value: float | int | str
    unit: Optional[str] = None


class Insight(BaseModel):
    """
    Stage 5 (schema_free_pipeline_design.md §5), LLM-reasoned revision: the
    insight-list response contract. Insights are no longer produced by a
    fixed set of rule-based category functions -- a single LLM call
    (app.insight_llm.generate_insights) reads whatever data this customer's
    tenant actually has (customer record, usage, tickets, catalog, latest
    recommendation, tenant-specific/"surprise" columns) and reasons out
    whichever handful of things actually matter, in its own words.

    Because of that:
      - `category` is free text chosen by the model for this insight (e.g.
        "risk", "revenue", "usage", or a tenant-specific label like
        "billing"), not a fixed enum -- the frontend picks a sensible
        default style for anything it doesn't recognize.
      - There is no `confidence` score. A non-technical reader has no use
        for a confidence percentage; if the data doesn't support a claim,
        the model simply doesn't make it (nothing is emitted as a
        placeholder).
      - There is no `source_columns`/`chain_of_thought` in the reader-facing
        payload -- an insight is either omitted or stated plainly, never
        hedged.
    """
    id: str
    category: str
    title: str
    summary: str
    metrics: list[InsightMetric] = []
    chart_hint: Optional[str] = None
