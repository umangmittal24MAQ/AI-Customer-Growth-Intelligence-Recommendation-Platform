"""
Vector Search Engine — OPTIONAL upgrade for product matching, same tier as
llm_engine.py: a tenant opts in explicitly (tenant_config.use_vector_search),
never a hard requirement to run the agent at all.

Why this exists: rule_engine.py's default keyword matching
(category -> ["security", "defender", "compliance"] etc.) works fine for a
hand-curated catalog of a dozen products, but doesn't scale to a catalog of
hundreds or thousands, where you can't maintain a keyword list by hand and
most products won't literally contain the keyword in their name.

Design choices, deliberately kept consistent with the rest of the project:
  - Runs 100% locally via sentence-transformers -- no API key, no per-call
    cost, works offline. This is what keeps it a genuine "optional upgrade"
    rather than a second hidden hard dependency.
  - Brute-force cosine similarity in numpy. At catalog sizes up to tens of
    thousands of products this is single-digit milliseconds -- no need for
    FAISS/pgvector/sqlite-vec until you're well past that.
  - Fails loudly with an actionable message if sentence-transformers isn't
    installed, rather than silently falling back -- silently downgrading a
    tenant who explicitly opted into vector search would misrepresent what
    they're paying for. Callers that want a fallback do it explicitly.
"""

import numpy as np

_model = None
_model_name = "all-MiniLM-L6-v2"
_available_cache = None  # None = not yet checked, True/False = cached result


def is_available() -> bool:
    """
    Cheap check the callers use before offering vector search.

    NOTE: `import sentence_transformers` pulls in torch as a dependency --
    on the very first call in a process this can take 10-30+ seconds
    (worse on CPU-only / Windows setups), even though nothing is being
    computed yet. That one-time cost used to be paid on EVERY call (e.g.
    every dashboard sidebar render), which could make a simple status
    check time out on the client even though the server was still working
    -- not actually unreachable, just slow. Caching the result after the
    first successful/failed import means only the very first check in the
    process's lifetime pays that cost; everything after is instant.
    """
    global _available_cache
    if _available_cache is not None:
        return _available_cache
    try:
        import sentence_transformers  # noqa: F401
        _available_cache = True
    except ImportError:
        _available_cache = False
    return _available_cache


def get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "Vector search requires the 'sentence-transformers' package. "
                "Install it with: pip install sentence-transformers"
            ) from e
        _model = SentenceTransformer(_model_name)
    return _model


def embed_text(text: str) -> np.ndarray:
    """Returns a normalized embedding (unit length), so cosine similarity == dot product."""
    vec = get_model().encode(text, normalize_embeddings=True)
    return np.asarray(vec, dtype=np.float32)


def product_embedding_text(product: dict) -> str:
    """
    Builds the text that gets embedded for a product. category/description
    are optional columns -- if a tenant hasn't filled them in, this still
    works off product_name alone, just with less semantic signal.
    """
    parts = [product.get("product_name", "")]
    if product.get("category"):
        parts.append(product["category"])
    if product.get("description"):
        parts.append(product["description"])
    return " — ".join(p for p in parts if p)


def embed_and_store_catalog(catalog: list[dict], tenant_id: str = "default") -> int:
    """Embeds every product in the catalog and persists it. Returns count embedded."""
    from app import db

    count = 0
    for product in catalog:
        text = product_embedding_text(product)
        vec = embed_text(text)
        db.save_product_embedding(tenant_id, product["product_id"], vec, text, _model_name)
        count += 1
    return count


def find_similar_products(query_text: str, catalog: list[dict], top_k: int = 3, tenant_id: str = "default") -> list[dict]:
    """
    Returns the top_k products from `catalog` whose stored embedding is most
    similar to query_text. Products in `catalog` that have no stored
    embedding yet are skipped (call embed_and_store_catalog first).
    """
    from app import db

    embeddings = db.get_all_product_embeddings(tenant_id)  # {product_id: np.ndarray}
    if not embeddings:
        return []

    catalog_by_id = {p["product_id"]: p for p in catalog}
    query_vec = embed_text(query_text)

    scored = [
        (pid, float(np.dot(query_vec, vec)))
        for pid, vec in embeddings.items()
        if pid in catalog_by_id
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    return [catalog_by_id[pid] for pid, _score in scored[:top_k]]


def catalog_needs_embedding(catalog: list[dict], tenant_id: str = "default") -> list[str]:
    """Returns product_ids in `catalog` that don't have a stored embedding yet."""
    from app import db

    embedded_ids = set(db.get_all_product_embeddings(tenant_id).keys())
    return [p["product_id"] for p in catalog if p["product_id"] not in embedded_ids]
