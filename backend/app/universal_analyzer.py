"""
Universal Analyzer – domain-agnostic signal extraction and scoring engine
for upsell opportunity prediction.

This module sits between ingestion (which normalises any dataset into
products / reviews / relationships) and the multi-agent recommendation
pipeline.  It provides:

    1. **Signal extraction** – derives numeric upsell/cross-sell signals from
       the product graph (price gaps, rating differentials, co-purchase
       frequency, category upgrade paths).

    2. **Opportunity scoring** – aggregates signals into a single 0-100
       *opportunity score* for each product pair (source → target).

    3. **Batch analysis** – scans the full product catalog for a tenant and
       returns a ranked list of upsell / cross-sell opportunities.

    4. **Dataset summary** – high-level statistics about the dataset to
       feed into the LLM pipeline for richer recommendations.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.logging_config import get_logger
from app import db
from app.domain_detector import (
    detect_domain_from_columns,
    detect_domain_from_dataframe,
    get_domain_analysis_config,
    DOMAIN_ECOMMERCE,
    DOMAIN_SAAS,
    DOMAIN_GENERIC,
)
from app.product_graph import (
    ProductGraph,
    build_graph_from_dataframes,
    compute_upsell_score,
    compute_cross_sell_score,
)
from app.ecommerce_ingestion import (
    detect_ecommerce_schema,
    extract_products,
    extract_reviews,
    extract_relationships,
    compute_review_stats,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Opportunity types
# ---------------------------------------------------------------------------

OPPORTUNITY_UPSELL = "upsell"          # same category, higher price/tier
OPPORTUNITY_CROSS_SELL = "cross_sell"   # complementary product
OPPORTUNITY_BUNDLE = "bundle"          # group-buy package


# ---------------------------------------------------------------------------
# Dataset summary
# ---------------------------------------------------------------------------

def build_dataset_summary(
    products: list[dict],
    reviews: list[dict],
    relationships: list[dict],
    review_stats: dict[str, dict],
    schema: dict,
    domain_info: dict,
) -> dict:
    """Build a high-level summary of the ingested dataset.

    This summary is used as context for the LLM recommendation pipeline.
    """
    prices = [p["price"] for p in products if p.get("price") is not None]
    ratings = [p.get("avg_rating") or p.get("rating")
               for p in products
               if (p.get("avg_rating") or p.get("rating")) is not None]
    categories = set(p.get("category") for p in products if p.get("category"))
    brands = set(p.get("brand") for p in products if p.get("brand"))

    rel_types: dict[str, int] = {}
    for r in relationships:
        rt = r.get("relationship_type", "unknown")
        rel_types[rt] = rel_types.get(rt, 0) + 1

    summary = {
        "domain": domain_info.get("domain", "generic"),
        "domain_confidence": domain_info.get("confidence", 0),
        "total_products": len(products),
        "total_reviews": len(reviews),
        "total_relationships": len(relationships),
        "relationship_types": rel_types,
        "price_range": {
            "min": round(min(prices), 2) if prices else None,
            "max": round(max(prices), 2) if prices else None,
            "mean": round(statistics.mean(prices), 2) if prices else None,
            "median": round(statistics.median(prices), 2) if prices else None,
        },
        "rating_range": {
            "min": round(min(ratings), 2) if ratings else None,
            "max": round(max(ratings), 2) if ratings else None,
            "mean": round(statistics.mean(ratings), 2) if ratings else None,
        },
        "categories_count": len(categories),
        "top_categories": sorted(categories)[:20],
        "brands_count": len(brands),
        "top_brands": sorted(brands)[:20],
        "detected_fields": schema.get("detected_fields", {}),
        "missing_fields": schema.get("missing_fields", []),
    }
    return summary


# ---------------------------------------------------------------------------
# Upsell opportunity discovery
# ---------------------------------------------------------------------------

def find_upsell_opportunities(
    graph: ProductGraph,
    max_per_product: int = 5,
    min_score: float = 20.0,
) -> list[dict]:
    """Scan the product graph for upsell opportunities.

    For each product, find higher-priced products in the same category
    that customers have viewed or purchased.

    Returns a list of opportunity dicts sorted by score (descending).
    """
    opportunities: list[dict] = []
    all_products = graph.product_info

    for pid, info in all_products.items():
        candidates = graph.get_upsell_candidates(pid, max_results=max_per_product)
        for c in candidates:
            score = c.get("score", 0)
            if score < min_score:
                continue
            target_info = c.get("product_info", {})
            opportunities.append({
                "type": OPPORTUNITY_UPSELL,
                "source_product_id": pid,
                "source_title": info.get("title", pid),
                "source_price": info.get("price"),
                "source_category": info.get("category"),
                "source_rating": info.get("rating"),
                "target_product_id": c.get("product_id", ""),
                "target_title": target_info.get("title", ""),
                "target_price": target_info.get("price"),
                "target_category": target_info.get("category"),
                "target_rating": target_info.get("rating"),
                "score": round(score, 1),
                "price_uplift": _price_uplift(info.get("price"),
                                              target_info.get("price")),
                "reasoning": _upsell_reasoning(info, target_info, score),
            })

    opportunities.sort(key=lambda x: x["score"], reverse=True)
    log.info("Found %d upsell opportunities", len(opportunities))
    return opportunities


def find_cross_sell_opportunities(
    graph: ProductGraph,
    max_per_product: int = 5,
    min_score: float = 15.0,
) -> list[dict]:
    """Scan the product graph for cross-sell opportunities.

    For each product, find complementary products that are frequently
    bought together.
    """
    opportunities: list[dict] = []
    all_products = graph.product_info

    for pid, info in all_products.items():
        candidates = graph.get_cross_sell_candidates(pid, max_results=max_per_product)
        for c in candidates:
            score = c.get("score", 0)
            if score < min_score:
                continue
            target_info = c.get("product_info", {})
            opportunities.append({
                "type": OPPORTUNITY_CROSS_SELL,
                "source_product_id": pid,
                "source_title": info.get("title", pid),
                "source_price": info.get("price"),
                "source_category": info.get("category"),
                "target_product_id": c.get("product_id", ""),
                "target_title": target_info.get("title", ""),
                "target_price": target_info.get("price"),
                "target_category": target_info.get("category"),
                "score": round(score, 1),
                "reasoning": _cross_sell_reasoning(info, target_info, score),
            })

    opportunities.sort(key=lambda x: x["score"], reverse=True)
    log.info("Found %d cross-sell opportunities", len(opportunities))
    return opportunities


# ---------------------------------------------------------------------------
# Full analysis pipeline
# ---------------------------------------------------------------------------

def analyze_dataset(
    tenant_id: str,
    df: pd.DataFrame,
    filename: str = "dataset",
    max_opportunities: int = 50,
) -> dict:
    """Run a full upsell/cross-sell analysis on a DataFrame.

    This is the main entry point for the universal analyzer.

    Steps:
        1. Detect domain
        2. Detect schema & extract products/reviews/relationships
        3. Build product graph
        4. Find upsell & cross-sell opportunities
        5. Generate dataset summary

    Returns a comprehensive analysis result dict.
    """
    log.info("Starting universal analysis for tenant=%s, file=%s (%d rows, %d cols)",
             tenant_id, filename, len(df), len(df.columns))

    # 1. Domain detection
    domain_info = detect_domain_from_dataframe(df, filename_hint=filename)
    domain = domain_info.get("domain", DOMAIN_GENERIC)
    log.info("Detected domain: %s (confidence=%.2f)", domain, domain_info.get("confidence", 0))

    # 2. Schema detection & extraction
    schema = detect_ecommerce_schema(df)
    products = extract_products(df, schema)
    reviews = extract_reviews(df, schema)
    relationships = extract_relationships(df, schema)
    review_stats = compute_review_stats(reviews)

    # Merge review stats into products
    for p in products:
        stats = review_stats.get(p["product_id"], {})
        p["avg_rating"] = stats.get("avg_rating", p.get("rating"))
        p["review_count"] = stats.get("review_count", 0)
        p["positive_pct"] = stats.get("positive_pct", 0)
        p["negative_pct"] = stats.get("negative_pct", 0)

    # 3. Build product graph
    graph = build_graph_from_dataframes(
        tenant_id,
        pd.DataFrame(products) if products else pd.DataFrame(),
        pd.DataFrame(reviews) if reviews else None,
    )
    graph_stats = graph.stats()

    # 4. Find opportunities
    upsell_opps = find_upsell_opportunities(
        graph, max_per_product=5, min_score=10.0
    )[:max_opportunities]
    cross_sell_opps = find_cross_sell_opportunities(
        graph, max_per_product=5, min_score=10.0
    )[:max_opportunities]

    # 5. Dataset summary
    dataset_summary = build_dataset_summary(
        products, reviews, relationships, review_stats, schema, domain_info
    )

    # 6. Category insights
    category_insights = _compute_category_insights(products, upsell_opps, cross_sell_opps)

    # 7. Top product insights
    top_products = _get_top_products(products, review_stats, limit=10)

    result = {
        "analysis_id": f"{tenant_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "tenant_id": tenant_id,
        "filename": filename,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "domain": domain_info,
        "dataset_summary": dataset_summary,
        "graph_stats": graph_stats,
        "upsell_opportunities": upsell_opps,
        "cross_sell_opportunities": cross_sell_opps,
        "total_upsell": len(upsell_opps),
        "total_cross_sell": len(cross_sell_opps),
        "category_insights": category_insights,
        "top_products": top_products,
        "status": "complete",
    }

    log.info("Analysis complete: %d upsells, %d cross-sells, %d products, %d categories",
             len(upsell_opps), len(cross_sell_opps),
             len(products), len(category_insights))

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _price_uplift(source_price: float | None, target_price: float | None) -> float | None:
    """Compute the price uplift percentage from source to target."""
    if not source_price or not target_price or source_price <= 0:
        return None
    return round((target_price - source_price) / source_price * 100, 1)


def _upsell_reasoning(source: dict, target: dict, score: float) -> str:
    """Generate a human-readable reasoning string for an upsell opportunity."""
    parts: list[str] = []
    sp = source.get("price")
    tp = target.get("price")
    if sp and tp:
        uplift = (tp - sp) / sp * 100 if sp > 0 else 0
        parts.append(f"Price upgrade of {uplift:.0f}% (${sp:.2f} → ${tp:.2f})")

    sr = source.get("rating") or source.get("avg_rating")
    tr = target.get("rating") or target.get("avg_rating")
    if sr and tr and tr > sr:
        parts.append(f"Higher rated ({sr:.1f} → {tr:.1f}★)")
    elif sr and tr and tr >= sr:
        parts.append(f"Maintains quality ({tr:.1f}★)")

    sc = source.get("category", "")
    tc = target.get("category", "")
    if sc and tc and sc == tc:
        parts.append(f"Same category ({sc})")
    elif tc:
        parts.append(f"Related category ({tc})")

    parts.append(f"Confidence score: {score:.0f}/100")
    return ". ".join(parts) + "."


def _cross_sell_reasoning(source: dict, target: dict, score: float) -> str:
    """Generate a human-readable reasoning string for a cross-sell opportunity."""
    parts: list[str] = []
    sc = source.get("category", "")
    tc = target.get("category", "")
    if sc and tc and sc != tc:
        parts.append(f"Complementary categories ({sc} + {tc})")
    elif sc and tc:
        parts.append(f"Frequently co-purchased in {sc}")

    tp = target.get("price")
    if tp:
        parts.append(f"Add-on price: ${tp:.2f}")

    tr = target.get("rating") or target.get("avg_rating")
    if tr:
        parts.append(f"Rated {tr:.1f}★")

    parts.append(f"Co-purchase score: {score:.0f}/100")
    return ". ".join(parts) + "."


def _compute_category_insights(
    products: list[dict],
    upsell_opps: list[dict],
    cross_sell_opps: list[dict],
) -> list[dict]:
    """Compute per-category insights from products and opportunities."""
    from collections import defaultdict

    cat_products: dict[str, list] = defaultdict(list)
    for p in products:
        cat = p.get("category")
        if cat:
            cat_products[cat].append(p)

    cat_upsell: dict[str, int] = defaultdict(int)
    cat_cross: dict[str, int] = defaultdict(int)

    for o in upsell_opps:
        cat = o.get("source_category")
        if cat:
            cat_upsell[cat] += 1

    for o in cross_sell_opps:
        cat = o.get("source_category")
        if cat:
            cat_cross[cat] += 1

    insights: list[dict] = []
    for cat, prods in cat_products.items():
        prices = [p["price"] for p in prods if p.get("price")]
        ratings = [p.get("avg_rating") or p.get("rating")
                   for p in prods
                   if (p.get("avg_rating") or p.get("rating")) is not None]
        insights.append({
            "category": cat,
            "product_count": len(prods),
            "avg_price": round(statistics.mean(prices), 2) if prices else None,
            "price_range": [round(min(prices), 2), round(max(prices), 2)] if prices else None,
            "avg_rating": round(statistics.mean(ratings), 2) if ratings else None,
            "upsell_opportunities": cat_upsell.get(cat, 0),
            "cross_sell_opportunities": cat_cross.get(cat, 0),
        })

    insights.sort(key=lambda x: x.get("upsell_opportunities", 0), reverse=True)
    return insights


def _get_top_products(
    products: list[dict],
    review_stats: dict[str, dict],
    limit: int = 10,
) -> list[dict]:
    """Get the top products by review count and rating."""
    scored: list[tuple[float, dict]] = []
    for p in products:
        pid = p["product_id"]
        stats = review_stats.get(pid, {})
        review_count = stats.get("review_count", 0)
        avg_rating = stats.get("avg_rating", 0)
        # Score: blend of popularity (review count) and quality (rating)
        score = review_count * 0.7 + avg_rating * 10 * 0.3
        scored.append((score, {
            "product_id": pid,
            "title": p.get("title"),
            "price": p.get("price"),
            "category": p.get("category"),
            "brand": p.get("brand"),
            "avg_rating": avg_rating,
            "review_count": review_count,
            "positive_pct": stats.get("positive_pct", 0),
            "score": round(score, 1),
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored[:limit]]


# ---------------------------------------------------------------------------
# Main (testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick test with synthetic e-commerce data
    test_df = pd.DataFrame({
        "asin": ["B001", "B002", "B003", "B004", "B005"],
        "title": [
            "Wireless Mouse Basic",
            "Wireless Mouse Pro",
            "Wireless Mouse Ultra",
            "Mouse Pad Standard",
            "USB-C Hub",
        ],
        "price": [15.99, 29.99, 49.99, 9.99, 24.99],
        "category": ["Electronics", "Electronics", "Electronics",
                      "Accessories", "Electronics"],
        "brand": ["TechBrand", "TechBrand", "TechBrand",
                  "AccBrand", "TechBrand"],
        "overall": [3.5, 4.2, 4.8, 4.0, 4.5],
        "reviewText": [
            "Basic mouse, works fine",
            "Great upgrade from the basic",
            "Best mouse I've ever used",
            "Good pad, nothing special",
            "Essential for my laptop",
        ],
        "reviewerID": ["U1", "U2", "U3", "U4", "U5"],
        "also_bought": [
            '["B002","B004"]', '["B003","B004"]',
            '["B004","B005"]', '["B001","B002"]', '["B003"]',
        ],
        "bought_together": [
            '["B004"]', '["B004"]', '["B004","B005"]', "[]", '["B003"]',
        ],
    })

    result = analyze_dataset("test-tenant", test_df, "test_products.json")

    print(f"\n{'='*60}")
    print(f"ANALYSIS RESULTS")
    print(f"{'='*60}")
    print(f"Domain: {result['domain']['domain']} "
          f"(confidence: {result['domain']['confidence']:.2f})")
    print(f"Products: {result['dataset_summary']['total_products']}")
    print(f"Graph: {result['graph_stats']}")
    print(f"\nUpsell Opportunities ({result['total_upsell']}):")
    for o in result["upsell_opportunities"][:5]:
        print(f"  {o['source_title']} → {o['target_title']} "
              f"(score={o['score']}, uplift={o['price_uplift']}%)")

    print(f"\nCross-Sell Opportunities ({result['total_cross_sell']}):")
    for o in result["cross_sell_opportunities"][:5]:
        print(f"  {o['source_title']} + {o['target_title']} "
              f"(score={o['score']})")

    print(f"\nCategory Insights:")
    for c in result["category_insights"]:
        print(f"  {c['category']}: {c['product_count']} products, "
              f"{c['upsell_opportunities']} upsells, "
              f"{c['cross_sell_opportunities']} cross-sells")
