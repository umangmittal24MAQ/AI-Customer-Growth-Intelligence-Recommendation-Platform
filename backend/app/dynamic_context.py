"""
Closes the loop between ingestion-time discovery (app.schema_mapping.
discover_unmapped_columns) and reasoning-time usage.

Previously, a discovered field like 'NPS' was stored in extra_attributes and
registered in dynamic_field_registry, but the only thing that ever read
dynamic_field_registry back out was GET /customer/{id}'s field_citations
(app/main.py) -- for a frontend hover/info-icon. None of pipeline.py,
rule_engine.py, or the IndiaAI agents (signal/retrieval/recommendation/critic)
actually looked at it, despite comments elsewhere implying they did.

This module is the missing piece: build_dynamic_field_context() turns a
tenant's registered dynamic fields into a compact, plain-language list for
whichever customer is currently being reasoned about, so it can be dropped
into the payload sent to any agent (or the rule engine, if you want it
there too -- not wired in by default since the rule engine is deterministic
code, not a model that can interpret free-form fields).

build_ticket_dynamic_field_context() does the same thing for dataset_type
"support_tickets". This is a separate table with its own extra_attributes
column (see data/schema.sql) -- a discovered column like "Priority_Score"
lives per-ticket, not per-customer, so it is NOT covered by
build_dynamic_field_context() even though the raw tickets list is already
included wholesale in build_signal_request()'s payload. Without this,
a ticket-level dynamic field's *value* technically reaches the model (as
an undescribed, doubly-JSON-encoded string buried in each ticket dict) but
with none of the semantic guidance (name/description/role) the customer-level
path gets from dynamic_field_registry -- the model has no way to know what
"Priority_Score" means or that it was worth paying attention to.
"""

import json

from app import db


def build_dynamic_field_context(
    tenant_id: str, customer: dict, dataset_type: str = "customers"
) -> list[dict]:
    """
    Returns [{field_name, description, value}, ...] for every dynamic field
    registered for this tenant/dataset that:
      (a) isn't classified 'ignore' (db.get_dynamic_fields already excludes
          these by default -- e.g. an internal tracking ID that carries no
          reasoning value), and
      (b) actually has a non-null value for THIS customer.

    (b) matters because dynamic_field_registry is tenant+dataset scoped, not
    per-customer -- if only some rows had a value for a discovered column,
    fields with nothing here don't add empty noise to the agent payload.

    Safe to call every time: reads two small tables, no LLM call, cheap
    enough to run per customer per pipeline run.
    """
    extra = customer.get("extra_attributes") or {}
    if not extra:
        return []

    fields = db.get_dynamic_fields(tenant_id, dataset_type=dataset_type, exclude_ignored=True)
    context = []
    for f in fields:
        value = extra.get(f["field_name"])
        if value is None:
            continue
        context.append({
            "field_name": f["field_name"],
            "description": f["description"],
            "value": value,
        })
    return context


def build_usage_dynamic_field_context(tenant_id: str, usage_rows: list[dict]) -> list[dict]:
    """
    Same idea as build_ticket_dynamic_field_context(), but for dataset_type
    "usage_metrics" -- e.g. a discovered column on a tenant's raw usage file
    (initech's renamed/extra usage columns are the motivating case). Returns
    one entry per (usage row, field) pair that has a value, tagged with the
    month it came from so a trend across months isn't collapsed into one
    ambiguous value:

        [{month, field_name, description, value}, ...]

    Unlike ticket rows, db.get_usage() already parses extra_attributes into
    a real dict (see app/db.py), so no defensive json.loads() is needed here.
    """
    fields = db.get_dynamic_fields(tenant_id, dataset_type="usage_metrics", exclude_ignored=True)
    if not fields:
        return []

    context = []
    for row in usage_rows:
        extra = row.get("extra_attributes") or {}
        for f in fields:
            value = extra.get(f["field_name"])
            if value is None:
                continue
            context.append({
                "month": row.get("month"),
                "field_name": f["field_name"],
                "description": f["description"],
                "value": value,
            })
    return context


def build_ticket_dynamic_field_context(tenant_id: str, tickets: list[dict]) -> list[dict]:
    """
    Same idea as build_dynamic_field_context(), but for dataset_type
    "support_tickets" -- e.g. a discovered "Priority_Score" column on a
    tenant's raw ticket file. Returns one entry per (ticket, field) pair
    that has a value, each tagged with which ticket it came from so the
    model can tell "Priority_Score: 4" apart on a specific ticket rather
    than a single ambiguous customer-wide value:

        [{ticket_id, field_name, description, value}, ...]

    extra_attributes on a ticket row from db.get_tickets() is the raw JSON
    TEXT column (not pre-parsed, unlike customer dicts which the rest of
    the codebase already builds as real dicts) -- parse it here defensively.
    """
    fields = db.get_dynamic_fields(tenant_id, dataset_type="support_tickets", exclude_ignored=True)
    if not fields:
        return []

    context = []
    for ticket in tickets:
        raw = ticket.get("extra_attributes")
        if not raw:
            continue
        extra = raw if isinstance(raw, dict) else json.loads(raw)
        for f in fields:
            value = extra.get(f["field_name"])
            if value is None:
                continue
            context.append({
                "ticket_id": ticket.get("ticket_id"),
                "field_name": f["field_name"],
                "description": f["description"],
                "value": value,
            })
    return context
