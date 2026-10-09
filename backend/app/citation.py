"""
Wraps any API-response value with a small "citation" envelope describing
where it came from -- a raw uploaded column, something computed/derived,
an LLM inference, or a tenant-specific dynamic field. This is the one
mechanism a future frontend hover/info-icon component binds to everywhere,
instead of each endpoint inventing its own ad-hoc explanation string.

Usage:
    with_citation(0.82, source="computed",
                  derivation="weighted average of service usage for 2026-06",
                  based_on=["service_usage.api_access", "service_usage.sso"])

    with_citation(customer["plan_tier"], source="raw_column",
                  derivation="mapped from tenant column 'Plan'")
"""

SOURCES = {"raw_column", "computed", "llm_inference", "dynamic_field"}


def with_citation(value, source: str, derivation: str = None, based_on: list = None,
                   confidence: float = None, field_description: str = None) -> dict:
    if source not in SOURCES:
        raise ValueError(f"Unknown citation source '{source}', expected one of {SOURCES}")
    return {
        "value": value,
        "citation": {
            "source": source,
            "derivation": derivation,
            "based_on": based_on or [],
            "confidence": confidence,
            "field_description": field_description,
        },
    }


def raw_column_citation(value, original_column: str = None):
    derivation = f"as provided by tenant upload, mapped from '{original_column}'" if original_column \
        else "as provided by tenant upload"
    return with_citation(value, source="raw_column", derivation=derivation)


def dynamic_field_citation(value, registry_entry: dict):
    """registry_entry is one row from app.db.get_dynamic_fields()."""
    return with_citation(
        value,
        source="dynamic_field",
        derivation=f"tenant-specific column '{registry_entry.get('source_column')}', "
                   f"classified as {registry_entry.get('semantic_role')}",
        confidence=registry_entry.get("confidence"),
        field_description=registry_entry.get("description"),
    )


def agent_trace_citation(value, agent_step: str, based_on: list, confidence: float = None):
    """For fields produced by reasoning (churn_risk, revenue_score, recommended_product, ...)."""
    return with_citation(
        value,
        source="llm_inference" if confidence is not None else "computed",
        derivation=f"produced by the '{agent_step}' step",
        based_on=based_on,
        confidence=confidence,
    )
