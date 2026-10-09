"""
Universal Pipeline – orchestration layer that ties together ingestion,
domain detection, graph construction, and analysis into a single
end-to-end workflow for any uploaded dataset.

This module provides:
    * ``run_universal_analysis`` – full pipeline from raw file bytes to results
    * ``run_analysis_on_dataframe`` – pipeline from a pre-loaded DataFrame
    * ``get_analysis_results`` – retrieve stored analysis results
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from typing import Any

from app.logging_config import get_logger
from app import db
from app.ecommerce_ingestion import read_ecommerce_file, IngestionError
from app.universal_analyzer import analyze_dataset

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pipeline status
# ---------------------------------------------------------------------------

class AnalysisStatus:
    PENDING = "pending"
    INGESTING = "ingesting"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_universal_analysis(
    tenant_id: str,
    filename: str,
    raw_bytes: bytes,
    dataset_label: str | None = None,
    max_opportunities: int = 50,
) -> dict:
    """Run the full universal analysis pipeline from raw file bytes.

    Steps:
        1. Parse file into DataFrame
        2. Run domain-agnostic analysis (detect domain, build graph,
           find opportunities)
        3. Store results
        4. Return comprehensive analysis results

    Args:
        tenant_id: Tenant/session identifier.
        filename: Original filename (used for format detection).
        raw_bytes: Raw file content.
        dataset_label: Optional human-readable label for the dataset.
        max_opportunities: Max number of each opportunity type to return.

    Returns:
        Analysis result dict with upsell/cross-sell opportunities,
        dataset summary, and category insights.
    """
    analysis_id = f"{tenant_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    label = dataset_label or filename

    log.info("Starting universal pipeline: analysis_id=%s, file=%s",
             analysis_id, filename)

    # Track status
    status_record = {
        "analysis_id": analysis_id,
        "tenant_id": tenant_id,
        "filename": filename,
        "label": label,
        "status": AnalysisStatus.PENDING,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # Step 1: Parse file
        status_record["status"] = AnalysisStatus.INGESTING
        log.info("[%s] Step 1: Parsing file...", analysis_id)
        df = read_ecommerce_file(filename, raw_bytes)
        log.info("[%s] Parsed %d rows × %d columns", analysis_id,
                 len(df), len(df.columns))

        # Step 2: Analyze
        status_record["status"] = AnalysisStatus.ANALYZING
        log.info("[%s] Step 2: Running analysis...", analysis_id)
        result = analyze_dataset(
            tenant_id=tenant_id,
            df=df,
            filename=filename,
            max_opportunities=max_opportunities,
        )

        # Enrich result
        result["analysis_id"] = analysis_id
        result["label"] = label
        result["status"] = AnalysisStatus.COMPLETE
        result["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Step 3: Persist results
        _persist_analysis(result)

        log.info("[%s] Pipeline complete: %d upsells, %d cross-sells",
                 analysis_id,
                 result.get("total_upsell", 0),
                 result.get("total_cross_sell", 0))

        return result

    except IngestionError as exc:
        log.error("[%s] Ingestion failed: %s", analysis_id, exc)
        return _error_result(analysis_id, tenant_id, filename, label,
                             f"File parsing failed: {exc}")
    except Exception as exc:
        log.error("[%s] Analysis failed: %s\n%s", analysis_id, exc,
                  traceback.format_exc())
        return _error_result(analysis_id, tenant_id, filename, label,
                             f"Analysis failed: {exc}")


def run_analysis_on_dataframe(
    tenant_id: str,
    df,  # pd.DataFrame
    filename: str = "uploaded_dataset",
    dataset_label: str | None = None,
    max_opportunities: int = 50,
) -> dict:
    """Run analysis on a pre-loaded DataFrame.

    Same as ``run_universal_analysis`` but skips the file parsing step.
    """
    analysis_id = f"{tenant_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    label = dataset_label or filename

    try:
        result = analyze_dataset(
            tenant_id=tenant_id,
            df=df,
            filename=filename,
            max_opportunities=max_opportunities,
        )
        result["analysis_id"] = analysis_id
        result["label"] = label
        result["status"] = AnalysisStatus.COMPLETE
        result["completed_at"] = datetime.now(timezone.utc).isoformat()

        _persist_analysis(result)
        return result

    except Exception as exc:
        log.error("[%s] DataFrame analysis failed: %s", analysis_id, exc)
        return _error_result(analysis_id, tenant_id, filename, label,
                             f"Analysis failed: {exc}")


# ---------------------------------------------------------------------------
# Result retrieval
# ---------------------------------------------------------------------------

# In-memory cache for analyses (supplement to DB storage)
_analysis_cache: dict[str, dict] = {}


def get_analysis_results(analysis_id: str) -> dict | None:
    """Retrieve stored analysis results by ID."""
    if analysis_id in _analysis_cache:
        return _analysis_cache[analysis_id]
    # Try DB
    try:
        row = db.get_dataset_analysis(analysis_id)
        if row:
            return row
    except Exception:
        pass
    return None


def list_analyses(tenant_id: str) -> list[dict]:
    """List all analyses for a tenant."""
    results = []
    for aid, data in _analysis_cache.items():
        if data.get("tenant_id") == tenant_id:
            results.append({
                "analysis_id": aid,
                "filename": data.get("filename"),
                "label": data.get("label"),
                "status": data.get("status"),
                "timestamp": data.get("timestamp"),
                "total_upsell": data.get("total_upsell", 0),
                "total_cross_sell": data.get("total_cross_sell", 0),
                "domain": data.get("domain", {}).get("domain", "unknown"),
            })
    # Also check DB
    try:
        db_results = db.list_dataset_analyses(tenant_id)
        if db_results:
            for r in db_results:
                if r.get("analysis_id") not in _analysis_cache:
                    results.append(r)
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _persist_analysis(result: dict) -> None:
    """Store analysis results in cache and attempt DB persistence."""
    aid = result.get("analysis_id", "unknown")
    _analysis_cache[aid] = result

    try:
        db.save_dataset_analysis(result)
    except Exception as exc:
        log.warning("Could not persist analysis %s to DB: %s", aid, exc)


def _error_result(
    analysis_id: str,
    tenant_id: str,
    filename: str,
    label: str,
    error_msg: str,
) -> dict:
    """Build a standardised error result."""
    result = {
        "analysis_id": analysis_id,
        "tenant_id": tenant_id,
        "filename": filename,
        "label": label,
        "status": AnalysisStatus.FAILED,
        "error": error_msg,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "upsell_opportunities": [],
        "cross_sell_opportunities": [],
        "total_upsell": 0,
        "total_cross_sell": 0,
        "dataset_summary": {},
        "category_insights": [],
        "top_products": [],
    }
    _analysis_cache[analysis_id] = result
    return result
