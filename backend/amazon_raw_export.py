"""
Raw, untouched export of Amazon-Reviews-2023 (McAuley Lab) into two plain
CSVs -- no renaming, no entity splitting, no invented columns. This is
deliberately as close as possible to "Amazon just handed you their CSV" so
you can see exactly how schema discovery (app/schema_discovery.py Stage 1)
reacts on its own: which columns it treats as concepts, what it picks as
the join key, and what dataset_label it assigns from content alone.

Run locally (huggingface.co isn't reachable from the sandbox that produced
this script). Requires: pip install datasets pandas

Usage:
    python amazon_raw_export.py --category All_Beauty --max-reviewers 75 --out-dir ./raw_amazon
"""

import argparse
import csv
import os
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default="All_Beauty")
    ap.add_argument("--max-reviewers", type=int, default=75,
                     help="Cap distinct user_ids kept -- biased toward reviewers with more history.")
    ap.add_argument("--out-dir", default="./raw_amazon")
    args = ap.parse_args()

    from datasets import load_dataset

    print(f"Loading raw_review_{args.category} ...")
    reviews = load_dataset(
        "McAuley-Lab/Amazon-Reviews-2023", f"raw_review_{args.category}",
        split="full", trust_remote_code=True,
    )
    print(f"Loading raw_meta_{args.category} ...")
    meta = load_dataset(
        "McAuley-Lab/Amazon-Reviews-2023", f"raw_meta_{args.category}",
        split="full", trust_remote_code=True,
    )

    os.makedirs(args.out_dir, exist_ok=True)

    # --- pick reviewers with more history so join_key resolution has ---
    # --- something to work with, otherwise leave every field untouched ---
    by_user = defaultdict(list)
    for r in reviews:
        uid = r.get("user_id")
        if uid:
            by_user[uid].append(r)
    top_users = sorted(by_user.items(), key=lambda kv: len(kv[1]), reverse=True)[: args.max_reviewers]
    kept_user_ids = {uid for uid, _ in top_users}

    review_fields = ["user_id", "parent_asin", "rating", "title", "text",
                      "timestamp", "verified_purchase", "helpful_vote"]
    reviews_path = os.path.join(args.out_dir, "reviews.csv")
    with open(reviews_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=review_fields, extrasaction="ignore")
        w.writeheader()
        for uid, rows in top_users:
            for r in rows:
                w.writerow({k: r.get(k, "") for k in review_fields})
    print(f"Wrote {reviews_path} ({sum(len(v) for _, v in top_users)} rows, {len(kept_user_ids)} distinct user_ids)")

    # Only keep metadata rows for products actually referenced by the kept
    # reviews -- otherwise the metadata file is enormous and mostly
    # irrelevant to this sample.
    referenced_asins = {r.get("parent_asin") for _, rows in top_users for r in rows if r.get("parent_asin")}
    meta_fields = ["parent_asin", "title", "main_category", "price",
                   "average_rating", "rating_number", "store", "categories"]
    meta_path = os.path.join(args.out_dir, "product_metadata.csv")
    seen = set()
    with open(meta_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=meta_fields, extrasaction="ignore")
        w.writeheader()
        for row in meta:
            asin = row.get("parent_asin")
            if asin not in referenced_asins or asin in seen:
                continue
            seen.add(asin)
            out = {k: row.get(k, "") for k in meta_fields}
            # categories often arrives as a list -- flatten so it's a plain
            # CSV cell, not a Python repr string, matching how a real
            # tenant's own export would look.
            if isinstance(out.get("categories"), list):
                out["categories"] = " > ".join(out["categories"])
            w.writerow(out)
    print(f"Wrote {meta_path} ({len(seen)} products)")

    print("\nNo renaming, no entity splitting, no invented columns -- exactly what came out of the dataset.")
    print("Now feed both files through Stage 1 discovery, e.g.:")
    print(f"""
python3 -c "
from app.schema_discovery import ingest_file
r1 = ingest_file('amazonbeauty', '{reviews_path}', 'reviews.csv')
print('reviews.csv ->', r1['dataset_label'], r1['join_key_column'])
r2 = ingest_file('amazonbeauty', '{meta_path}', 'product_metadata.csv')
print('product_metadata.csv ->', r2['dataset_label'], r2['join_key_column'])
"
""")


if __name__ == "__main__":
    main()