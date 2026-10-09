"""
Runs every CSV under data/tenant_uploads/<tenant_id>/<dataset_type>.csv
through one of two pipelines that already exist in the codebase:

  Legacy fixed-schema flow (default):
    onboard_tenant()        -- fuzzy (+ optional LLM) column-mapping suggestion
    save_column_mapping()   -- confirm the mapping for this tenant/dataset
    ingest_file()           -- apply mapping, validate, upsert rows, and run
                                discover_unmapped_columns() on anything left over
    Kept for the legacy fixed-schema tenants and for tests
    (scripts/migrate_to_schema_free.py) -- not the path new tenants take.

  Schema-free flow (--schema-free):
    ingest_all_files_for_tenant_schema_free() -- the same Stage 1 -> 2 -> 3
    entry point app/onboarding.py calls on every new-tenant login (schema
    discovery -> prompt architect compile -> bounded self-correction). Use
    this flag to manually re-run ingestion the same way login would.

In a real product the legacy flow's "confirm the mapping" step would be a
human clicking "looks good" in an onboarding UI. Here we auto-confirm every
suggested mapping so the whole flow can run unattended for a demo/test.
Required fields that come back unmapped are NOT auto-confirmed -- those are
reported and skipped, exactly like a human reviewer would need to fix them
by hand before ingestion could succeed. (Not applicable in --schema-free
mode, which has no fixed fields to map.)

Usage:
    python scripts/run_tenant_ingestion.py
    python scripts/run_tenant_ingestion.py --use-llm       # legacy-only: try IndiaAI mapping, needs env vars set
    python scripts/run_tenant_ingestion.py --tenant acme   # just one tenant
    python scripts/run_tenant_ingestion.py --schema-free   # run the schema-free flow instead (matches login behavior)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db
from app.data_ingestion import ingest_file, IngestionError
from app.schema_mapping import onboard_tenant, save_column_mapping

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "tenant_uploads")


def discover_tenant_files(only_tenant: str | None = None):
    """Yields (tenant_id, dataset_type, filepath) for every CSV found."""
    if not os.path.isdir(UPLOADS_DIR):
        return
    for tenant_id in sorted(os.listdir(UPLOADS_DIR)):
        if only_tenant and tenant_id != only_tenant:
            continue
        tenant_dir = os.path.join(UPLOADS_DIR, tenant_id)
        if not os.path.isdir(tenant_dir):
            continue
        for fname in sorted(os.listdir(tenant_dir)):
            if fname.endswith(".csv"):
                dataset_type = fname[: -len(".csv")]
                yield tenant_id, dataset_type, os.path.join(tenant_dir, fname)


def process_one(tenant_id: str, dataset_type: str, filepath: str, use_llm: bool) -> dict:
    import pandas as pd

    raw_columns = list(pd.read_csv(filepath, nrows=0).columns)

    # Step 1 -- suggest a mapping (fuzzy always runs; LLM only if requested
    # and IndiaAI env vars are configured).
    suggestion = onboard_tenant(tenant_id, raw_columns, use_llm=use_llm, dataset_type=dataset_type)

    if suggestion["unmapped_required_fields"]:
        return {
            "tenant_id": tenant_id,
            "dataset_type": dataset_type,
            "status": "skipped",
            "reason": f"required field(s) still unmapped after suggestion: "
                      f"{suggestion['unmapped_required_fields']} "
                      f"(try --use-llm, or extend KNOWN_ALIASES in app/schema_mapping.py)",
            "suggested_mapping": suggestion["suggested_mapping"],
            "mapping_source": suggestion["mapping_source"],
        }

    # Step 2 -- confirm it. (Stands in for a human clicking "confirm" in an
    # onboarding page.)
    save_column_mapping(tenant_id, dataset_type, suggestion["suggested_mapping"], confirmed=True)

    # Step 3 -- ingest. This is where apply_mapping(), validate_columns(),
    # the upsert, and discover_unmapped_columns() all happen.
    with open(filepath, "rb") as f:
        raw_bytes = f.read()
    try:
        result = ingest_file(tenant_id, dataset_type, os.path.basename(filepath), raw_bytes)
    except IngestionError as e:
        return {"tenant_id": tenant_id, "dataset_type": dataset_type, "status": "error", "reason": str(e)}

    result["mapping_source"] = suggestion["mapping_source"]
    result["mapping_used"] = suggestion["suggested_mapping"]
    result["status"] = "ok"
    return result


def ingest_all_files_for_tenant(tenant_id: str, use_llm: bool = False) -> list[dict]:
    """Importable entry point: ingests every CSV under
    data/tenant_uploads/<tenant_id>/ for one tenant. Used by both this CLI
    script and the auto-ingest-on-login flow in app/onboarding.py -- kept
    here so there is exactly one place that knows how to walk mapping ->
    confirm -> ingest_file() for a tenant's raw files.
    """
    db.init_db()
    results = []
    for t_id, dataset_type, filepath in discover_tenant_files(tenant_id):
        results.append(process_one(t_id, dataset_type, filepath, use_llm=use_llm))
    return results


def ingest_all_files_for_tenant_schema_free(tenant_id: str) -> dict:
    """
    Schema-free ingestion entry point (replaces ingest_all_files_for_tenant's
    fixed-schema mapping -> confirm -> ingest_file flow for new tenants --
    see schema_free_pipeline_design.md).

    Runs, per tenant, in order:
      Stage 1 -- schema_discovery.ingest_file() for every uploaded file
                 (column inference, no fixed FIELD_DEFINITIONS involved).
      Stage 2 -- prompt_architect.compile_if_stale() to (re)compile the
                 cached tenant-specific instruction block.
      Stage 3 -- schema_self_correction.run_self_correction() to sample-check
                 the compiled schema+prompt against a few real customers and
                 resolve/record any gaps before it's treated as final.

    Never blocks on a single file failing to parse -- other files for the
    same tenant still get a chance to ingest, matching the old flow's
    per-file independence.
    """
    from app import schema_discovery, prompt_architect, schema_self_correction

    db.init_db()
    file_results = []
    for t_id, dataset_type, filepath in discover_tenant_files(tenant_id):
        try:
            result = schema_discovery.ingest_file(t_id, filepath, os.path.basename(filepath), dataset_type)
            file_results.append({"tenant_id": t_id, "filename": os.path.basename(filepath),
                                  "status": "ok", "dataset_label": result["dataset_label"],
                                  "changed": result["changed"], "column_count": len(result["columns"])})
        except Exception as e:
            file_results.append({"tenant_id": t_id, "filename": os.path.basename(filepath),
                                  "status": "error", "reason": str(e)})

    if not file_results:
        return {"tenant_id": tenant_id, "files": [], "prompt_spec_compiled": False, "self_correction": None}

    spec = prompt_architect.compile_if_stale(tenant_id)
    correction = schema_self_correction.run_self_correction(tenant_id)

    return {
        "tenant_id": tenant_id,
        "files": file_results,
        "prompt_spec_compiled": True,
        "possible_insight_categories": spec["possible_insight_categories"],
        "self_correction": correction,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-free", action="store_true",
                         help="Use the schema-free pipeline (Stage 1 discovery -> Stage 2 prompt "
                              "architect -> Stage 3 self-correction) instead of the legacy "
                              "fixed-schema mapping flow -- the same path app/onboarding.py runs "
                              "on new-tenant login.")
    parser.add_argument("--use-llm", action="store_true",
                         help="Legacy flow only: also try the IndiaAI mapping step for "
                              "columns fuzzy matching can't resolve. Ignored with --schema-free.")
    parser.add_argument("--tenant", default=None, help="Only process this tenant_id.")
    args = parser.parse_args()

    db.init_db()  # safe/idempotent -- creates tables if missing, never drops data

    files = list(discover_tenant_files(args.tenant))
    if not files:
        print(f"No tenant CSVs found under {os.path.abspath(UPLOADS_DIR)}. "
              f"Run data/generate_tenant_csvs.py first.")
        return

    if args.schema_free:
        tenants = sorted({tenant_id for tenant_id, _, _ in files})
        print(f"Found {len(files)} tenant file(s) across {len(tenants)} tenant(s). "
              f"Running schema-free pipeline.\n")
        for tenant_id in tenants:
            print(f"--- {tenant_id} (schema-free) ---")
            result = ingest_all_files_for_tenant_schema_free(tenant_id)
            for f in result["files"]:
                if f["status"] == "ok":
                    print(f"  {f['filename']}: dataset='{f['dataset_label']}', "
                          f"columns={f['column_count']}, changed={f['changed']}")
                else:
                    print(f"  {f['filename']}: ERROR -- {f['reason']}")
            if result["prompt_spec_compiled"]:
                print(f"  possible insight categories: {result['possible_insight_categories']}")
                print(f"  self-correction: {result['self_correction']}")
            print()
        print("Done (schema-free).")
        return

    print(f"Found {len(files)} tenant file(s). LLM mapping: {'ON' if args.use_llm else 'OFF (fuzzy-only)'}\n")

    results = []
    for tenant_id, dataset_type, filepath in files:
        print(f"--- {tenant_id} / {dataset_type} ---")
        result = process_one(tenant_id, dataset_type, filepath, use_llm=args.use_llm)
        results.append(result)

        if result["status"] == "ok":
            print(f"  mapping used   : {result['mapping_used']}")
            print(f"  mapping source : {result['mapping_source']}")
            print(f"  rows ingested  : {result['rows_ingested']}")
            print(f"  new fields discovered : {result['new_fields_discovered']}")
            if result["new_fields_discovered"]:
                fields = db.get_dynamic_fields(tenant_id, dataset_type)
                for f in fields:
                    print(f"    - {f['field_name']} (from '{f['source_column']}') "
                          f"-> relevance={f['relevance']}, type={f['inferred_type']}: {f['description']}")
        else:
            print(f"  status: {result['status']} -- {result['reason']}")
        print()

    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"Done. {ok}/{len(results)} file(s) ingested successfully.")
    print("Run scripts/generate_dynamic_fields_report.py to see all discovered fields per tenant.")


if __name__ == "__main__":
    main()
