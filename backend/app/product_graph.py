"""
Product Relationship Graph -- in-memory directed graph that captures how
products relate to each other (co-purchase, browsing similarity, upsell
paths, complementary categories) and exposes fast queries for upsell,
cross-sell, and bundle suggestions.

The graph is intentionally simple: a dict-of-dicts adjacency list with typed,
weighted edges.  No external graph library is required, which keeps the
deployment footprint tiny and the logic fully transparent.

Usage::

    from app.product_graph import build_graph_from_db, build_graph_from_dataframes

    # Option A -- build from the SQLite tables that data_ingestion already populates
    graph = build_graph_from_db("tenant-42")

    # Option B -- build directly from pandas DataFrames (e.g. during onboarding)
    graph = build_graph_from_dataframes("tenant-42", products_df, reviews_df)

    upsells    = graph.get_upsell_candidates("B001")
    cross_sell = graph.get_cross_sell_candidates("B001")
    bundle     = graph.get_bundle_suggestions(["B001", "B002"])
"""

from __future__ import annotations

import json
from collections import defaultdict

from app.logging_config import get_logger
from app import db

log = get_logger(__name__)

# ── Relationship type constants ───────────────────────────────────────────

REL_BOUGHT_TOGETHER = "bought_together"           # Strong cross-sell
REL_ALSO_BOUGHT = "also_bought"                   # Moderate cross-sell
REL_ALSO_VIEWED = "also_viewed"                   # Browsing similarity
REL_BUY_AFTER_VIEWING = "buy_after_viewing"       # Conversion/upsell path
REL_SAME_CATEGORY_UPGRADE = "same_category_upgrade"  # Upsell
REL_COMPLEMENTARY = "complementary"               # Cross-category cross-sell

_ALL_REL_TYPES = {
    REL_BOUGHT_TOGETHER,
    REL_ALSO_BOUGHT,
    REL_ALSO_VIEWED,
    REL_BUY_AFTER_VIEWING,
    REL_SAME_CATEGORY_UPGRADE,
    REL_COMPLEMENTARY,
}


# ── Helpers for safe numeric access ───────────────────────────────────────

def _float(value, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ── ProductGraph ──────────────────────────────────────────────────────────

class ProductGraph:
    """In-memory directed graph of product relationships.

    Nodes carry arbitrary product metadata (title, price, category, brand,
    rating, ...).  Edges are typed and weighted, supporting fast neighbour
    look-ups filtered by relationship kind.
    """

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id: str = tenant_id
        # adjacency: source_id -> list of {target_id, rel_type, weight}
        self.adjacency: dict[str, list[dict]] = defaultdict(list)
        # product_info: product_id -> dict of metadata
        self.product_info: dict[str, dict] = {}

    # ── Node / edge mutators ──────────────────────────────────────────

    def add_product(self, product_id: str, info: dict) -> None:
        """Add (or update) a product node with its metadata.

        Parameters
        ----------
        product_id:
            Unique product identifier.
        info:
            Arbitrary metadata -- commonly includes *title*, *price*,
            *category*, *brand*, *rating*, *review_count*, etc.
        """
        self.product_info[product_id] = info

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        weight: float = 1.0,
    ) -> None:
        """Add a directed edge from *source_id* to *target_id*.

        Parameters
        ----------
        rel_type:
            One of the ``REL_*`` constants defined in this module.
        weight:
            Edge strength (default 1.0).  Higher means a stronger signal.
        """
        self.adjacency[source_id].append(
            {"target_id": target_id, "rel_type": rel_type, "weight": weight}
        )

    # ── Queries ───────────────────────────────────────────────────────

    def get_neighbors(
        self, product_id: str, rel_type: str | None = None
    ) -> list[dict]:
        """Return adjacent products, optionally filtered by *rel_type*.

        Each element is::

            {
                "product_id": str,
                "rel_type": str,
                "weight": float,
                "product_info": dict | None,
            }
        """
        edges = self.adjacency.get(product_id, [])
        results: list[dict] = []
        for edge in edges:
            if rel_type is not None and edge["rel_type"] != rel_type:
                continue
            results.append(
                {
                    "product_id": edge["target_id"],
                    "rel_type": edge["rel_type"],
                    "weight": edge["weight"],
                    "product_info": self.product_info.get(edge["target_id"]),
                }
            )
        return results

    def get_upsell_candidates(
        self, product_id: str, max_results: int = 5
    ) -> list[dict]:
        """Products that are potential upgrades for *product_id*.

        Only considers products in the same category with a higher price or
        better rating.  Each candidate is scored 0-100:

        * ``price_ratio``            x 0.3
        * ``rating_diff``            x 0.2
        * ``also_viewed_weight``     x 0.3
        * ``buy_after_viewing_weight`` x 0.2

        Returns up to *max_results* candidates sorted by score descending.
        """
        source = self.product_info.get(product_id)
        if not source:
            log.warning("get_upsell_candidates: unknown product %s", product_id)
            return []

        source_price = _float(source.get("price"))
        source_rating = _float(source.get("rating"))
        source_category = (source.get("category") or "").lower().strip()

        # Pre-index neighbour weights keyed by (target_id, rel_type).
        edge_index: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        for edge in self.adjacency.get(product_id, []):
            edge_index[edge["target_id"]][edge["rel_type"]] = max(
                edge_index[edge["target_id"]][edge["rel_type"]], edge["weight"]
            )

        candidates: list[dict] = []
        for pid, info in self.product_info.items():
            if pid == product_id:
                continue
            target_category = (info.get("category") or "").lower().strip()
            if source_category and target_category and target_category != source_category:
                continue

            target_price = _float(info.get("price"))
            target_rating = _float(info.get("rating"))

            # Must be an *upgrade* -- higher price or better rating.
            if target_price <= source_price and target_rating <= source_rating:
                continue

            edge_weights = edge_index.get(pid, {})
            score = compute_upsell_score(source, info, edge_weights)
            candidates.append(
                {
                    "product_id": pid,
                    "score": round(score, 2),
                    "product_info": info,
                    "edge_weights": dict(edge_weights),
                }
            )

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:max_results]

    def get_cross_sell_candidates(
        self, product_id: str, max_results: int = 5
    ) -> list[dict]:
        """Products frequently bought together with or co-purchased after
        *product_id*.

        Scoring (0-100):

        * ``bought_together_weight``   x 0.4
        * ``also_bought_weight``       x 0.3
        * ``complementary_weight``     x 0.3

        Returns up to *max_results* candidates sorted by score descending.
        """
        source = self.product_info.get(product_id)
        if not source:
            log.warning("get_cross_sell_candidates: unknown product %s", product_id)
            return []

        edge_index: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        for edge in self.adjacency.get(product_id, []):
            edge_index[edge["target_id"]][edge["rel_type"]] = max(
                edge_index[edge["target_id"]][edge["rel_type"]], edge["weight"]
            )

        candidates: list[dict] = []
        for target_id, weights in edge_index.items():
            if target_id == product_id:
                continue
            # At least one cross-sell signal must be present.
            if not (
                weights.get(REL_BOUGHT_TOGETHER)
                or weights.get(REL_ALSO_BOUGHT)
                or weights.get(REL_COMPLEMENTARY)
            ):
                continue

            target_info = self.product_info.get(target_id, {})
            score = compute_cross_sell_score(source, target_info, weights)
            candidates.append(
                {
                    "product_id": target_id,
                    "score": round(score, 2),
                    "product_info": target_info,
                    "edge_weights": dict(weights),
                }
            )

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:max_results]

    def get_bundle_suggestions(
        self, product_ids: list[str], max_results: int = 5
    ) -> list[dict]:
        """Given a set of products (e.g. a shopping cart), find products that
        complement the *entire* set.

        Score = sum of co-purchase weights across all input products.  Products
        already in the input set are excluded.
        """
        input_set = set(product_ids)
        # Accumulate weights per candidate across all input products.
        candidate_scores: dict[str, float] = defaultdict(float)
        for pid in product_ids:
            for edge in self.adjacency.get(pid, []):
                tid = edge["target_id"]
                if tid in input_set:
                    continue
                if edge["rel_type"] in (
                    REL_BOUGHT_TOGETHER,
                    REL_ALSO_BOUGHT,
                    REL_COMPLEMENTARY,
                ):
                    candidate_scores[tid] += edge["weight"]

        sorted_candidates = sorted(
            candidate_scores.items(), key=lambda kv: kv[1], reverse=True
        )[:max_results]

        results: list[dict] = []
        for tid, score in sorted_candidates:
            results.append(
                {
                    "product_id": tid,
                    "score": round(score, 2),
                    "product_info": self.product_info.get(tid),
                }
            )
        return results

    def get_product_info(self, product_id: str) -> dict | None:
        """Return stored metadata for *product_id*, or ``None``."""
        return self.product_info.get(product_id)

    def stats(self) -> dict:
        """Summary statistics for the graph.

        Returns::

            {"nodes": int, "edges": int, "edge_type_counts": {str: int}}
        """
        total_edges = 0
        edge_type_counts: dict[str, int] = defaultdict(int)
        for edges in self.adjacency.values():
            for edge in edges:
                total_edges += 1
                edge_type_counts[edge["rel_type"]] += 1
        return {
            "nodes": len(self.product_info),
            "edges": total_edges,
            "edge_type_counts": dict(edge_type_counts),
        }


# ── Scoring helpers ───────────────────────────────────────────────────────

def compute_upsell_score(
    source_info: dict, target_info: dict, edge_weights: dict
) -> float:
    """Compute a 0-100 score for the upsell potential from *source* to *target*.

    Factors
    -------
    * **price_ratio** -- ``target / source`` price.  The sweet spot for upsell
      is 1.1x-3x; above 3x the jump feels too big, below 1.1x there is no
      meaningful upgrade.
    * **rating_improvement** -- positive delta in star rating.
    * **browsing_conversion_signal** -- ``also_viewed`` edge weight.
    * **category_match** -- bonus when both products share a category.

    Returns
    -------
    float
        Score in [0, 100].
    """
    source_price = _float(source_info.get("price"), 1.0)
    target_price = _float(target_info.get("price"), 0.0)
    source_rating = _float(source_info.get("rating"))
    target_rating = _float(target_info.get("rating"))

    # -- price ratio component (0-100) --
    if source_price > 0 and target_price > 0:
        ratio = target_price / source_price
        # Ideal range 1.1-3.0; score peaks near 1.5x.
        if ratio < 1.0:
            price_score = 0.0
        elif ratio <= 1.5:
            price_score = (ratio - 1.0) / 0.5 * 100.0
        elif ratio <= 3.0:
            price_score = max(0.0, 100.0 - (ratio - 1.5) / 1.5 * 60.0)
        else:
            price_score = max(0.0, 40.0 - (ratio - 3.0) * 10.0)
    else:
        price_score = 0.0

    # -- rating improvement (0-100) --
    rating_diff = target_rating - source_rating
    rating_score = min(100.0, max(0.0, rating_diff * 20.0))

    # -- browsing/conversion signals (0-100 each) --
    also_viewed_w = _float(edge_weights.get(REL_ALSO_VIEWED))
    bav_w = _float(edge_weights.get(REL_BUY_AFTER_VIEWING))
    also_viewed_score = min(100.0, also_viewed_w * 100.0)
    bav_score = min(100.0, bav_w * 100.0)

    # Weighted sum as specified:
    # price_ratio * 0.3 + rating_diff * 0.2 + also_viewed * 0.3 + bav * 0.2
    raw = (
        price_score * 0.3
        + rating_score * 0.2
        + also_viewed_score * 0.3
        + bav_score * 0.2
    )
    return min(100.0, max(0.0, raw))


def compute_cross_sell_score(
    source_info: dict, target_info: dict, edge_weights: dict
) -> float:
    """Compute a 0-100 score for cross-sell potential.

    Factors
    -------
    * **co_purchase_frequency** -- ``bought_together`` edge weight.
    * **complementary_category_signal** -- ``complementary`` edge weight.
    * **price_compatibility** -- products in a similar price range pair better.
    * **rating_quality** -- higher-rated targets are preferred.

    Returns
    -------
    float
        Score in [0, 100].
    """
    bt_w = _float(edge_weights.get(REL_BOUGHT_TOGETHER))
    ab_w = _float(edge_weights.get(REL_ALSO_BOUGHT))
    comp_w = _float(edge_weights.get(REL_COMPLEMENTARY))

    co_purchase_score = min(100.0, bt_w * 100.0)
    also_bought_score = min(100.0, ab_w * 100.0)
    complementary_score = min(100.0, comp_w * 100.0)

    # Weighted sum as specified:
    # bought_together * 0.4 + also_bought * 0.3 + complementary * 0.3
    raw = (
        co_purchase_score * 0.4
        + also_bought_score * 0.3
        + complementary_score * 0.3
    )

    # Bonus adjustments for price compatibility and rating quality.
    source_price = _float(source_info.get("price"), 1.0)
    target_price = _float(target_info.get("price"), 0.0)
    target_rating = _float(target_info.get("rating"))

    if source_price > 0 and target_price > 0:
        price_ratio = min(source_price, target_price) / max(source_price, target_price)
        # price_ratio near 1.0 => similar price => good cross-sell pairing.
        raw += price_ratio * 5.0  # up to +5 bonus

    if target_rating > 0:
        raw += min(5.0, target_rating)  # up to +5 bonus for high-rated target

    return min(100.0, max(0.0, raw))


# ── Graph builders ────────────────────────────────────────────────────────

def build_graph_from_db(tenant_id: str) -> ProductGraph:
    """Build a :class:`ProductGraph` from the SQLite tables.

    Loads products via ``db.get_product_catalog`` and, for schema-free
    tenants, falls back to ``db.get_dataset_rows``.  Relationship edges are
    not yet stored in a dedicated table, so this builder creates
    ``SAME_CATEGORY_UPGRADE`` edges automatically from the catalog.
    """
    graph = ProductGraph(tenant_id)

    # -- Load product nodes ------------------------------------------------
    products = db.get_product_catalog(tenant_id)
    if not products:
        log.info("build_graph_from_db: no catalog rows for tenant %s", tenant_id)
        return graph

    for prod in products:
        pid = str(
            prod.get("product_id")
            or prod.get("asin")
            or prod.get("id")
            or ""
        )
        if not pid:
            continue
        info = {
            "title": prod.get("product_name") or prod.get("title") or "",
            "price": _float(prod.get("price_per_seat") or prod.get("price")),
            "category": prod.get("category") or "",
            "brand": prod.get("brand") or "",
            "rating": _float(prod.get("rating") or prod.get("overall")),
            "tier_level": prod.get("tier_level") or prod.get("product_tier_level"),
        }
        # Merge any remaining keys as extra metadata.
        for k, v in prod.items():
            if k not in info and k != "tenant_id":
                info[k] = v
        graph.add_product(pid, info)

    # -- Auto-generate same-category upgrade edges -------------------------
    _auto_generate_upgrade_edges(graph)

    log.info(
        "build_graph_from_db: tenant=%s  %s",
        tenant_id,
        json.dumps(graph.stats(), default=str),
    )
    return graph


def build_graph_from_dataframes(
    tenant_id: str,
    products_df,
    reviews_df=None,
    relationships_df=None,
) -> ProductGraph:
    """Build a :class:`ProductGraph` directly from pandas DataFrames.

    Parameters
    ----------
    products_df:
        Must contain at least a product identifier column.  Column names are
        auto-detected using common naming patterns (``product_id``, ``asin``,
        ``id``; ``price``, ``price_per_seat``; ``category``, ``group``; etc.).
    reviews_df:
        Optional.  If provided, average ratings are computed per product and
        merged into node metadata.
    relationships_df:
        Optional.  Explicit relationship rows with columns like
        ``source_id``, ``target_id``, ``rel_type``, ``weight``.

    Relationship lists embedded in *products_df* (e.g. ``also_bought``,
    ``bought_together`` columns containing JSON arrays) are also extracted.
    """
    import pandas as pd  # local import -- not all callers use pandas

    graph = ProductGraph(tenant_id)

    if products_df is None or products_df.empty:
        log.info("build_graph_from_dataframes: empty products_df")
        return graph

    cols = {c.lower().strip(): c for c in products_df.columns}

    # -- Detect column names -----------------------------------------------
    id_col = _detect_column(cols, ["product_id", "asin", "id", "productid", "item_id", "sku"])
    title_col = _detect_column(cols, ["title", "product_name", "name", "productname", "description"])
    price_col = _detect_column(cols, ["price", "price_per_seat", "unit_price", "cost", "msrp"])
    category_col = _detect_column(cols, ["category", "categories", "group", "product_group", "department"])
    brand_col = _detect_column(cols, ["brand", "manufacturer", "vendor"])
    rating_col = _detect_column(cols, ["rating", "overall", "avg_rating", "average_rating", "stars"])

    if not id_col:
        log.warning("build_graph_from_dataframes: no product-id column detected")
        return graph

    log.info(
        "build_graph_from_dataframes: detected columns -- id=%s title=%s price=%s "
        "category=%s brand=%s rating=%s",
        id_col, title_col, price_col, category_col, brand_col, rating_col,
    )

    # -- Aggregate ratings from reviews_df if provided ---------------------
    review_ratings: dict[str, float] = {}
    if reviews_df is not None and not reviews_df.empty:
        rev_cols = {c.lower().strip(): c for c in reviews_df.columns}
        rev_id_col = _detect_column(rev_cols, ["product_id", "asin", "item_id", "productid"])
        rev_rating_col = _detect_column(rev_cols, ["rating", "overall", "score", "stars", "review_score"])
        if rev_id_col and rev_rating_col:
            try:
                avg = reviews_df.groupby(rev_id_col)[rev_rating_col].mean()
                review_ratings = avg.to_dict()
                log.info("build_graph_from_dataframes: computed ratings for %d products from reviews", len(review_ratings))
            except Exception:
                log.exception("build_graph_from_dataframes: failed to compute review ratings")

    # -- Add product nodes -------------------------------------------------
    for _, row in products_df.iterrows():
        pid = str(row.get(id_col, ""))
        if not pid:
            continue
        info: dict = {
            "title": str(row.get(title_col, "")) if title_col else "",
            "price": _float(row.get(price_col)) if price_col else 0.0,
            "category": str(row.get(category_col, "")) if category_col else "",
            "brand": str(row.get(brand_col, "")) if brand_col else "",
            "rating": _float(row.get(rating_col)) if rating_col else 0.0,
        }
        # Override with review-derived rating if available.
        if pid in review_ratings:
            info["rating"] = round(review_ratings[pid], 2)

        graph.add_product(pid, info)

        # -- Extract embedded relationship lists ---------------------------
        _extract_embedded_relationships(graph, pid, row, cols)

    # -- Add edges from explicit relationships_df --------------------------
    if relationships_df is not None and not relationships_df.empty:
        rel_cols = {c.lower().strip(): c for c in relationships_df.columns}
        src_col = _detect_column(rel_cols, ["source_id", "source", "product_id", "from_id", "asin"])
        tgt_col = _detect_column(rel_cols, ["target_id", "target", "to_id", "related_asin", "related_product_id"])
        rt_col = _detect_column(rel_cols, ["rel_type", "relationship", "type", "relation"])
        wt_col = _detect_column(rel_cols, ["weight", "score", "strength", "confidence"])

        if src_col and tgt_col:
            for _, row in relationships_df.iterrows():
                src = str(row.get(src_col, ""))
                tgt = str(row.get(tgt_col, ""))
                rt = str(row.get(rt_col, REL_ALSO_BOUGHT)) if rt_col else REL_ALSO_BOUGHT
                wt = _float(row.get(wt_col, 1.0)) if wt_col else 1.0
                if src and tgt:
                    graph.add_edge(src, tgt, rt, wt)

    # -- Auto-generate same-category upgrade edges -------------------------
    _auto_generate_upgrade_edges(graph)

    log.info(
        "build_graph_from_dataframes: tenant=%s  %s",
        tenant_id,
        json.dumps(graph.stats(), default=str),
    )
    return graph


# ── Internal helpers ──────────────────────────────────────────────────────

def _detect_column(
    cols_lower_map: dict[str, str],
    candidates: list[str],
) -> str | None:
    """Return the *original* column name matching the first candidate found,
    or ``None``.

    ``cols_lower_map`` maps ``lower(column)`` -> ``original_column``.
    """
    for candidate in candidates:
        if candidate in cols_lower_map:
            return cols_lower_map[candidate]
    return None


def _extract_embedded_relationships(
    graph: ProductGraph,
    product_id: str,
    row,
    cols_lower_map: dict[str, str],
) -> None:
    """If columns like ``also_bought``, ``bought_together``, ``also_viewed``,
    or ``buy_after_viewing`` exist and contain JSON lists, parse them and add
    the corresponding edges.
    """
    rel_column_mapping = {
        "also_bought": REL_ALSO_BOUGHT,
        "bought_together": REL_BOUGHT_TOGETHER,
        "also_viewed": REL_ALSO_VIEWED,
        "buy_after_viewing": REL_BUY_AFTER_VIEWING,
    }

    for col_pattern, rel_type in rel_column_mapping.items():
        original_col = cols_lower_map.get(col_pattern)
        if not original_col:
            continue
        raw = row.get(original_col)
        if raw is None:
            continue
        related_ids = _parse_id_list(raw)
        for rid in related_ids:
            graph.add_edge(product_id, rid, rel_type, weight=1.0)


def _parse_id_list(value) -> list[str]:
    """Best-effort parse of a value that should be a list of product IDs.

    Handles: Python list, JSON string, comma-separated string, NaN.
    """
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        value = value.strip()
        if not value or value.lower() == "nan":
            return []
        # Try JSON first.
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v]
        except (json.JSONDecodeError, TypeError):
            pass
        # Fall back to comma-separated.
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def _auto_generate_upgrade_edges(graph: ProductGraph) -> None:
    """For every pair of products in the same category, add a
    ``SAME_CATEGORY_UPGRADE`` edge from the cheaper to the more expensive
    product (only when the price difference is meaningful).
    """
    by_category: dict[str, list[str]] = defaultdict(list)
    for pid, info in graph.product_info.items():
        cat = (info.get("category") or "").lower().strip()
        if cat:
            by_category[cat].append(pid)

    edges_added = 0
    for cat, pids in by_category.items():
        if len(pids) < 2:
            continue
        # Sort by price ascending.
        priced = [
            (pid, _float(graph.product_info[pid].get("price")))
            for pid in pids
        ]
        priced.sort(key=lambda x: x[1])

        for i, (src_id, src_price) in enumerate(priced):
            if src_price <= 0:
                continue
            for tgt_id, tgt_price in priced[i + 1:]:
                if tgt_price <= src_price:
                    continue
                ratio = tgt_price / src_price
                # Only generate an edge if the upgrade is between 1.1x and 5x.
                if 1.1 <= ratio <= 5.0:
                    # Weight inversely proportional to the price gap (closer
                    # upgrades feel more natural).
                    weight = max(0.1, 1.0 - (ratio - 1.0) / 4.0)
                    graph.add_edge(
                        src_id, tgt_id, REL_SAME_CATEGORY_UPGRADE, weight
                    )
                    edges_added += 1

    if edges_added:
        log.info(
            "_auto_generate_upgrade_edges: added %d upgrade edges across %d categories",
            edges_added,
            len(by_category),
        )


# ── Main (demo / smoke test) ─────────────────────────────────────────────

if __name__ == "__main__":
    """Build a small test graph and print upsell / cross-sell candidates."""

    g = ProductGraph(tenant_id="demo")

    # -- Add some products --
    g.add_product("A1", {"title": "Basic Headphones",   "price": 29.99, "category": "audio", "brand": "SoundCo", "rating": 3.8})
    g.add_product("A2", {"title": "Pro Headphones",     "price": 79.99, "category": "audio", "brand": "SoundCo", "rating": 4.5})
    g.add_product("A3", {"title": "Studio Headphones",  "price": 199.99, "category": "audio", "brand": "SoundCo", "rating": 4.8})
    g.add_product("B1", {"title": "Phone Case",         "price": 15.99, "category": "accessories", "brand": "CaseCo", "rating": 4.2})
    g.add_product("B2", {"title": "Screen Protector",   "price": 9.99,  "category": "accessories", "brand": "ShieldCo", "rating": 4.0})
    g.add_product("C1", {"title": "USB-C Cable",        "price": 12.99, "category": "cables", "brand": "WireCo", "rating": 4.3})

    # -- Add some relationships --
    g.add_edge("A1", "A2", REL_ALSO_VIEWED, 0.8)
    g.add_edge("A1", "A2", REL_BUY_AFTER_VIEWING, 0.6)
    g.add_edge("A1", "B1", REL_BOUGHT_TOGETHER, 0.7)
    g.add_edge("A1", "C1", REL_ALSO_BOUGHT, 0.5)
    g.add_edge("B1", "B2", REL_BOUGHT_TOGETHER, 0.9)
    g.add_edge("B1", "C1", REL_COMPLEMENTARY, 0.6)
    g.add_edge("A2", "A3", REL_ALSO_VIEWED, 0.7)

    # -- Auto-generate upgrade edges --
    _auto_generate_upgrade_edges(g)

    print("=== Graph Stats ===")
    print(json.dumps(g.stats(), indent=2))

    print("\n=== Upsell Candidates for A1 (Basic Headphones) ===")
    for c in g.get_upsell_candidates("A1"):
        print(f"  {c['product_id']}: {c['product_info']['title']}  "
              f"score={c['score']}  edges={c['edge_weights']}")

    print("\n=== Cross-sell Candidates for A1 (Basic Headphones) ===")
    for c in g.get_cross_sell_candidates("A1"):
        print(f"  {c['product_id']}: {c['product_info']['title']}  "
              f"score={c['score']}  edges={c['edge_weights']}")

    print("\n=== Bundle Suggestions for cart [A1, B1] ===")
    for c in g.get_bundle_suggestions(["A1", "B1"]):
        print(f"  {c['product_id']}: {c['product_info']['title']}  "
              f"score={c['score']}")
