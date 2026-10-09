"""
E-commerce Data Ingestion – handles ingestion of e-commerce datasets
(like Amazon UCSD product data) into the system.

Supports:
    * CSV, JSON, JSON-lines (.jsonl), and Excel file formats
    * Auto-detection of schema columns (product_id, title, price, etc.)
    * Extraction of product relationships (also_bought, bought_together, etc.)
    * Review statistics computation
    * Robust price parsing from various formats
"""

from __future__ import annotations

import csv
import io
import ast
import json
import re
from typing import Any

import pandas as pd

from app.logging_config import get_logger
from app import db

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IngestionError(Exception):
    """Raised when a file cannot be parsed into a DataFrame."""


# ---------------------------------------------------------------------------
# Column name pattern maps – order matters (first match wins)
# ---------------------------------------------------------------------------

FIELD_PATTERNS: dict[str, list[str]] = {
    "product_id": [
        "asin", "parent_asin", "product_id", "item_id", "sku",
        "productid", "item_number", "product_code",
    ],
    "title": [
        "title", "product_title", "name", "product_name", "item_name",
    ],
    "price": [
        "price", "list_price", "sale_price", "current_price",
        "unit_price", "retail_price",
    ],
    "category": [
        "category", "categories", "main_category", "department",
        "product_category", "product_group",
    ],
    "brand": [
        "brand", "manufacturer", "seller", "store", "vendor",
    ],
    "rating": [
        "rating", "overall", "average_rating", "score", "stars",
        "avg_rating", "review_rating",
    ],
    "review_text": [
        "text", "review_text", "reviewtext", "comment", "body",
        "review_body", "review_content", "summary",
    ],
    "user_id": [
        "user_id", "reviewer_id", "reviewerid", "customer_id",
        "userid", "customerid", "buyer_id",
    ],
    "also_bought": ["also_bought", "alsobought"],
    "bought_together": ["bought_together", "boughttogether"],
    "also_viewed": ["also_viewed", "alsoviewed"],
    "buy_after_viewing": ["buy_after_viewing", "buyafterviewing"],
    "timestamp": [
        "timestamp", "date", "review_date", "unixreviewtime",
        "reviewtime", "created_at", "purchase_date",
    ],
    "verified": [
        "verified", "verified_purchase", "verifiedpurchase",
    ],
    "helpful_votes": [
        "helpful", "helpful_votes", "helpfulness", "helpful_vote",
    ],
    "description": [
        "description", "product_description", "details",
    ],
    "features": [
        "feature", "features", "product_features",
    ],
    "images": [
        "image", "images", "imurl", "imageurl", "image_url",
    ],
}


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def read_ecommerce_file(filename: str, raw_bytes: bytes) -> pd.DataFrame:
    """Read an uploaded file into a pandas DataFrame.

    Supports CSV, JSON (array-of-objects or single object), JSON-lines, and
    Excel (.xlsx / .xls).

    Raises:
        IngestionError: if the file cannot be parsed.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    log.info("Reading e-commerce file '%s' (extension=%s, %d bytes)",
             filename, ext, len(raw_bytes))

    try:
        if ext in ("csv", "tsv"):
            sep = "\t" if ext == "tsv" else ","
            return pd.read_csv(io.BytesIO(raw_bytes), sep=sep,
                               on_bad_lines="skip", engine="python")

        if ext == "jsonl":
            return _read_jsonl(raw_bytes)

        if ext == "json":
            return _read_json(raw_bytes)

        if ext in ("xlsx", "xls"):
            return pd.read_excel(io.BytesIO(raw_bytes))

        # Fallback: try CSV, then JSON-lines
        try:
            return pd.read_csv(io.BytesIO(raw_bytes), on_bad_lines="skip",
                               engine="python")
        except Exception:
            return _read_jsonl(raw_bytes)

    except Exception as exc:
        raise IngestionError(
            f"Failed to parse '{filename}': {exc}"
        ) from exc


def _read_jsonl(raw_bytes: bytes) -> pd.DataFrame:
    """Parse newline-delimited JSON (JSON-lines)."""
    records: list[dict] = []
    for line in raw_bytes.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not records:
        raise IngestionError("No valid JSON records found in JSONL file")
    return pd.json_normalize(records)


def _read_json(raw_bytes: bytes) -> pd.DataFrame:
    """Parse a plain JSON file (array-of-objects or single object)."""
    text = raw_bytes.decode("utf-8", errors="replace")
    data = json.loads(text)
    if isinstance(data, list):
        return pd.json_normalize(data)
    if isinstance(data, dict):
        # Could be {key: [records]} or a single object
        for val in data.values():
            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                return pd.json_normalize(val)
        return pd.json_normalize([data])
    raise IngestionError("Unexpected JSON root type")


# ---------------------------------------------------------------------------
# Schema detection
# ---------------------------------------------------------------------------

def detect_ecommerce_schema(df: pd.DataFrame) -> dict:
    """Auto-detect which columns map to semantic fields.

    Returns::

        {
            "detected_fields": {"product_id": "asin", "title": "title", ...},
            "missing_fields": ["brand", ...],
            "extra_fields": ["some_column", ...],
        }
    """
    norm_cols = {c.lower().strip().replace(" ", "_"): c for c in df.columns}
    detected: dict[str, str] = {}
    matched_original: set[str] = set()

    for field, patterns in FIELD_PATTERNS.items():
        for pat in patterns:
            # exact match
            if pat in norm_cols:
                detected[field] = norm_cols[pat]
                matched_original.add(norm_cols[pat])
                break
            # substring match
            for ncol, orig in norm_cols.items():
                if pat in ncol and orig not in matched_original:
                    detected[field] = orig
                    matched_original.add(orig)
                    break
            if field in detected:
                break

    missing = [f for f in FIELD_PATTERNS if f not in detected]
    extra = [c for c in df.columns if c not in matched_original]

    log.info("Schema detection: %d fields mapped, %d missing, %d extra",
             len(detected), len(missing), len(extra))
    return {
        "detected_fields": detected,
        "missing_fields": missing,
        "extra_fields": extra,
    }


# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(r"[\d]+\.?\d*")


def parse_price(value: Any) -> float | None:
    """Parse a price from various formats.

    Handles: ``'$19.99'``, ``19.99``, ``'$12.34 - $45.67'`` (takes lower),
    ``None``, ``''``, and numeric types.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    s = str(value).strip()
    if not s:
        return None
    matches = _PRICE_RE.findall(s)
    if matches:
        return float(matches[0])
    return None


# ---------------------------------------------------------------------------
# Relationship extraction
# ---------------------------------------------------------------------------

def _parse_list_column(value: Any) -> list[str]:
    """Robustly parse a column value that should be a list of IDs.

    Handles JSON arrays, Python repr lists, pipe/comma-delimited strings,
    and already-parsed lists.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]

    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "[]", "{}"):
        return []

    # JSON array
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v]
        except json.JSONDecodeError:
            pass
        # Python repr fallback
        try:
            parsed = ast.literal_eval(s)  # Accept only Python literals, never execute input
            if isinstance(parsed, (list, tuple)):
                return [str(v) for v in parsed if v]
        except Exception:
            pass

    # Pipe-delimited
    if "|" in s:
        return [p.strip() for p in s.split("|") if p.strip()]

    # Comma-delimited
    if "," in s:
        return [p.strip() for p in s.split(",") if p.strip()]

    # Single value
    return [s] if s else []


def extract_relationships(df: pd.DataFrame, schema: dict) -> list[dict]:
    """Extract relationship edges from also_bought, bought_together, etc.

    Returns a list of ``{source_id, target_id, relationship_type, weight}``
    dicts.
    """
    detected = schema.get("detected_fields", {})
    pid_col = detected.get("product_id")
    if not pid_col:
        log.warning("No product_id column detected – cannot extract relationships")
        return []

    rel_map = {
        "also_bought":       ("also_bought",       0.6),
        "bought_together":   ("bought_together",   0.9),
        "also_viewed":       ("also_viewed",       0.3),
        "buy_after_viewing": ("buy_after_viewing",  0.7),
    }

    edges: list[dict] = []
    for field, (rel_type, weight) in rel_map.items():
        col = detected.get(field)
        if not col or col not in df.columns:
            continue
        for _, row in df.iterrows():
            source = str(row.get(pid_col, "")).strip()
            if not source:
                continue
            targets = _parse_list_column(row.get(col))
            for target in targets:
                edges.append({
                    "source_id": source,
                    "target_id": target,
                    "relationship_type": rel_type,
                    "weight": weight,
                })

    log.info("Extracted %d relationship edges", len(edges))
    return edges


# ---------------------------------------------------------------------------
# Product extraction
# ---------------------------------------------------------------------------

def extract_products(df: pd.DataFrame, schema: dict) -> list[dict]:
    """Extract normalised product records from the DataFrame.

    Deduplicates by product_id.  Returns a list of dicts with keys:
    ``product_id``, ``title``, ``price``, ``category``, ``brand``,
    ``rating``, ``description``, ``features``.
    """
    detected = schema.get("detected_fields", {})
    pid_col = detected.get("product_id")
    if not pid_col:
        log.warning("No product_id column – cannot extract products")
        return []

    field_map = {
        "title": detected.get("title"),
        "price": detected.get("price"),
        "category": detected.get("category"),
        "brand": detected.get("brand"),
        "rating": detected.get("rating"),
        "description": detected.get("description"),
        "features": detected.get("features"),
    }

    seen: set[str] = set()
    products: list[dict] = []
    for _, row in df.iterrows():
        pid = str(row.get(pid_col, "")).strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)

        product: dict[str, Any] = {"product_id": pid}
        for key, col in field_map.items():
            if col and col in df.columns:
                val = row.get(col)
                if key == "price":
                    val = parse_price(val)
                elif key == "rating":
                    try:
                        val = float(val) if val is not None and str(val).strip() else None
                    except (ValueError, TypeError):
                        val = None
                elif key == "features":
                    val = _parse_list_column(val)
                else:
                    val = str(val).strip() if val is not None and str(val).strip() else None
                product[key] = val
            else:
                product[key] = None

        products.append(product)

    log.info("Extracted %d unique products", len(products))
    return products


# ---------------------------------------------------------------------------
# Review extraction
# ---------------------------------------------------------------------------

def extract_reviews(df: pd.DataFrame, schema: dict) -> list[dict]:
    """Extract review records from the DataFrame.

    Returns a list of dicts with keys: ``user_id``, ``product_id``,
    ``rating``, ``text``, ``timestamp``, ``verified``, ``helpful_votes``.
    """
    detected = schema.get("detected_fields", {})
    pid_col = detected.get("product_id")
    uid_col = detected.get("user_id")
    if not pid_col:
        log.warning("No product_id column – cannot extract reviews")
        return []

    field_map = {
        "rating": detected.get("rating"),
        "text": detected.get("review_text"),
        "timestamp": detected.get("timestamp"),
        "verified": detected.get("verified"),
        "helpful_votes": detected.get("helpful_votes"),
    }

    reviews: list[dict] = []
    for _, row in df.iterrows():
        pid = str(row.get(pid_col, "")).strip()
        if not pid:
            continue
        uid = str(row.get(uid_col, "")).strip() if uid_col else None

        review: dict[str, Any] = {"product_id": pid, "user_id": uid}
        for key, col in field_map.items():
            if col and col in df.columns:
                val = row.get(col)
                if key == "rating":
                    try:
                        val = float(val) if val is not None and str(val).strip() else None
                    except (ValueError, TypeError):
                        val = None
                elif key == "helpful_votes":
                    try:
                        val = int(val) if val is not None and str(val).strip() else 0
                    except (ValueError, TypeError):
                        val = 0
                elif key == "verified":
                    val = str(val).lower() in ("true", "1", "yes") if val else False
                else:
                    val = str(val).strip() if val is not None else None
                review[key] = val
            else:
                review[key] = None

        reviews.append(review)

    log.info("Extracted %d reviews", len(reviews))
    return reviews


# ---------------------------------------------------------------------------
# Review statistics
# ---------------------------------------------------------------------------

def compute_review_stats(reviews: list[dict]) -> dict[str, dict]:
    """Compute per-product review statistics.

    Returns a dict keyed by product_id with values::

        {
            "avg_rating": float,
            "review_count": int,
            "positive_pct": float,  # rating >= 4
            "negative_pct": float,  # rating <= 2
        }
    """
    from collections import defaultdict

    buckets: dict[str, list[float]] = defaultdict(list)
    for r in reviews:
        pid = r.get("product_id")
        rating = r.get("rating")
        if pid and rating is not None:
            buckets[pid].append(rating)

    stats: dict[str, dict] = {}
    for pid, ratings in buckets.items():
        count = len(ratings)
        avg = sum(ratings) / count
        positive = sum(1 for r in ratings if r >= 4)
        negative = sum(1 for r in ratings if r <= 2)
        stats[pid] = {
            "avg_rating": round(avg, 2),
            "review_count": count,
            "positive_pct": round(positive / count * 100, 1),
            "negative_pct": round(negative / count * 100, 1),
        }

    return stats


# ---------------------------------------------------------------------------
# Full ingestion pipeline
# ---------------------------------------------------------------------------

def ingest_ecommerce_dataset(
    tenant_id: str,
    filename: str,
    raw_bytes: bytes,
    dataset_label: str | None = None,
) -> dict:
    """End-to-end ingestion of an e-commerce dataset.

    1. Parse file → DataFrame
    2. Detect schema
    3. Extract products, reviews, relationships
    4. Compute review stats
    5. Store in database

    Returns a summary dict.
    """
    df = read_ecommerce_file(filename, raw_bytes)
    schema = detect_ecommerce_schema(df)

    products = extract_products(df, schema)
    reviews = extract_reviews(df, schema)
    relationships = extract_relationships(df, schema)
    review_stats = compute_review_stats(reviews)

    # Persist products
    for p in products:
        pid = p["product_id"]
        stats = review_stats.get(pid, {})
        p["avg_rating"] = stats.get("avg_rating")
        p["review_count"] = stats.get("review_count", 0)
        p["positive_pct"] = stats.get("positive_pct", 0)
        p["negative_pct"] = stats.get("negative_pct", 0)

    # Store via db functions (graceful fallback if tables not ready)
    stored_products = 0
    stored_rels = 0
    try:
        for p in products:
            db.upsert_product(tenant_id, p)
            stored_products += 1
    except Exception as exc:
        log.warning("Could not persist products to DB: %s", exc)

    try:
        for rel in relationships:
            db.insert_product_relationship(
                tenant_id,
                rel["source_id"],
                rel["target_id"],
                rel["relationship_type"],
                rel["weight"],
            )
            stored_rels += 1
    except Exception as exc:
        log.warning("Could not persist relationships to DB: %s", exc)

    summary = {
        "filename": filename,
        "label": dataset_label or filename,
        "rows": len(df),
        "columns": list(df.columns),
        "detected_fields": schema["detected_fields"],
        "missing_fields": schema["missing_fields"],
        "products_extracted": len(products),
        "reviews_extracted": len(reviews),
        "relationships_extracted": len(relationships),
        "products_stored": stored_products,
        "relationships_stored": stored_rels,
        "review_stats_count": len(review_stats),
    }
    log.info("Ingestion complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Main (testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick smoke test with synthetic data
    test_data = pd.DataFrame({
        "asin": ["B001", "B002", "B003", "B001"],
        "title": ["Widget A", "Widget B Pro", "Widget C Premium", "Widget A"],
        "price": ["$19.99", "$29.99", "$49.99", "$19.99"],
        "category": ["Electronics", "Electronics", "Electronics", "Electronics"],
        "brand": ["BrandX", "BrandX", "BrandY", "BrandX"],
        "overall": [4.0, 4.5, 3.5, 5.0],
        "reviewText": ["Great product", "Better than A", "Overpriced", "Love it"],
        "reviewerID": ["U1", "U2", "U3", "U4"],
        "also_bought": ['["B002","B003"]', '["B001"]', '["B002"]', '["B003"]'],
        "bought_together": ['["B002"]', "[]", '["B001"]', "[]"],
    })

    schema = detect_ecommerce_schema(test_data)
    print("=== Schema Detection ===")
    for k, v in schema.items():
        print(f"  {k}: {v}")

    products = extract_products(test_data, schema)
    print(f"\n=== Products ({len(products)}) ===")
    for p in products:
        print(f"  {p['product_id']}: {p['title']} @ {p['price']}")

    reviews = extract_reviews(test_data, schema)
    print(f"\n=== Reviews ({len(reviews)}) ===")

    rels = extract_relationships(test_data, schema)
    print(f"\n=== Relationships ({len(rels)}) ===")
    for r in rels[:5]:
        print(f"  {r['source_id']} --[{r['relationship_type']}]--> {r['target_id']}")

    stats = compute_review_stats(reviews)
    print(f"\n=== Review Stats ===")
    for pid, s in stats.items():
        print(f"  {pid}: {s}")
