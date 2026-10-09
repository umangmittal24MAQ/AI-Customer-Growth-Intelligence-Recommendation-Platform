import json
import os
import uuid
from datetime import datetime
from typing import Optional
from app.logging_config import get_logger
from app import db

log = get_logger(__name__)

_sessions: dict = {}
_MAX_HISTORY = 20


def _get_indiaai_client():
    from app.indiaai_client import optional_client
    from app.config import LLM_MODEL
    try:
        return optional_client(), LLM_MODEL
    except (RuntimeError, ImportError) as exc:
        log.warning("IndiaAI chat unavailable: %s", exc)
        return None, None


# All valid intent labels — used to validate LLM output
_VALID_INTENTS = frozenset({
    "small_talk", "analytics", "batch_run",
    "churn_list", "medium_risk_list", "low_risk_list",
    "top_recommendations", "highest_revenue", "churn_revenue_calc",
    "customer_lookup", "recommendation", "recommendation_benefits",
    "filter_by_plan", "filter_by_recommended_product", "subscription_filter",
    "no_upsell_customers", "top_products_by_segment",
    "catalog_query", "feature_weights",
    "send_email", "schedule_meeting",
    "compound_churn_action", "custom_rec_and_regenerate",
    "unknown",
})

_INTENT_PROMPT = """You are an expert intent classifier for a B2B sales-assistant chatbot. Read the user's message and reply with EXACTLY ONE label from the list — lowercase, no punctuation, no explanation, no quotes.

LABELS (pick the single best match):
small_talk           — greetings, chitchat, thanks, "what can you do", "who are you"
analytics            — AGGREGATE metrics about the whole book of business: overview, summary, dashboard, how many customers, total/overall revenue opportunity, recommendation distribution
batch_run            — run/generate/refresh recommendations for ALL customers at once
churn_list           — list HIGH churn / high risk / at-risk customers
medium_risk_list     — list MEDIUM / moderate churn risk customers (optionally with their recommendations)
low_risk_list        — list LOW churn / stable / safe customers (optionally with their recommendations)
top_recommendations  — the top-N highest-confidence recommendations across all customers
highest_revenue      — the SINGLE customer (or ranked few) with the biggest deal value / revenue opportunity
customer_lookup      — view / show / profile a specific NAMED customer (no explicit ask to generate)
recommendation       — get or generate an upsell recommendation for a specific NAMED customer
recommendation_benefits — WHY a recommendation was made / its rationale / benefits for a customer
filter_by_plan       — customers on a specific plan tier (enterprise, professional, starter, basic)
filter_by_recommended_product — customers who were recommended a specific product
subscription_filter  — customers subscribed to product X but NOT product Y
no_upsell_customers  — customers that should NOT be upsold / recommendation suppressed
top_products_by_segment — the most popular / top-selling products overall
catalog_query        — list the products available in the catalog
feature_weights      — feature weights / scoring priority / importance settings
send_email           — send a recommendation email to a customer
schedule_meeting     — schedule / book a meeting or call with a customer
compound_churn_action — a MULTI-STEP query: high-churn customers AND email above a confidence threshold AND/OR schedule meetings above a value threshold
churn_revenue_calc   — the total/aggregate revenue opportunity coming FROM high-churn customers (revenue + churn together)
custom_rec_and_regenerate — add a specific product as a custom recommendation for eligible customers and regenerate
unknown              — none of the above

DISAMBIGUATION RULES:
- "total / overall / combined revenue opportunity" (no single customer) => analytics. "which customer / biggest / highest deal value" => highest_revenue. But "revenue opportunity FROM high churn customers" OR "upsell value from top N high churn" => churn_revenue_calc.
- A specific customer NAME with "show / view / profile / tell me about" => customer_lookup. With "recommend / upsell / what should we sell" => recommendation. With "why / rationale / benefit" => recommendation_benefits.
- "who is using / customers with / who bought / customers recommended" => filter_by_recommended_product. If checking a subscription plan (like basic, starter, enterprise) => filter_by_plan.
- Be careful with "recommendation" vs "top_recommendations". If they ask for "top X recommendations", it is "top_recommendations". If they ask for a recommendation for ONE specific customer, it's "recommendation".
- "medium / moderate risk ... and recommend top 3 products for each" => medium_risk_list (the "top 3 products" is per-customer, NOT top_recommendations).
- If the message asks to email OR schedule for a GROUP of high-churn customers based on thresholds => compound_churn_action. A single named customer email/meeting => send_email / schedule_meeting.
- "should not be upsold / no upsell / avoid upselling" => no_upsell_customers (never churn_list).
- "analyze / run / evaluate ALL or EVERY customer" => batch_run (running the analysis job), NOT analytics (analytics is only for reading existing aggregate metrics).

EXAMPLES:
"how many customers are at high risk overall" => analytics
"which account has the largest upsell value" => highest_revenue
"revenue we could recover from at-risk accounts" => churn_revenue_calc
"list moderate risk sellers and their top 3 product picks" => medium_risk_list
"why did you suggest FBA for Galaxy Electronics" => recommendation_benefits
"email everyone with high churn and over 70% confidence" => compound_churn_action
"who is on the enterprise tier" => filter_by_plan
"analyze every customer" => batch_run
"re-run the analysis for all accounts" => batch_run
"what can this assistant do" => small_talk"""


def _llm_classify_intent(message: str) -> str | None:
    """Fast LLM-based intent classification. Returns None on any failure."""
    client, deployment = _get_indiaai_client()
    if not client:
        return None
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": _INTENT_PROMPT},
                {"role": "user", "content": message},
            ],
            max_tokens=160,
            temperature=0,
            timeout=25.0,
        )
        label = resp.choices[0].message.content.strip().lower().split()[0]
        return label if label in _VALID_INTENTS else None
    except Exception as e:
        log.debug("LLM intent classification failed: %s", e)
        return None


def _keyword_classify_intent(message: str) -> str:
    """Keyword-based fallback classifier used when LLM is unavailable."""
    msg = message.lower().strip()

    small_talk_exact = ["hello", "hi", "hey", "how are you", "what's up", "good morning",
                        "good afternoon", "good evening", "thanks", "thank you", "bye",
                        "goodbye", "what can you do", "who are you"]
    if any(msg == k or msg.startswith(k + " ") for k in small_talk_exact):
        return "small_talk"
    if len(msg) < 20 and any(k in msg for k in ["hi", "hello", "hey", "thanks", "bye"]):
        return "small_talk"

    import re as _re_kw

    # Compound churn + email + meeting query — MUST come before churn_revenue_calc
    has_churn = any(k in msg for k in ["high churn", "high risk", "at-risk", "at risk", "churn risk", "churn"])
    has_email = any(k in msg for k in ["email", "send email", "confidence score", "confidence above"])
    has_meet  = any(k in msg for k in ["meeting", "schedule"])
    if has_churn and (has_email or has_meet):
        return "compound_churn_action"

    # churn_revenue_calc: "upsell value / revenue / deal value from high churn" — only if no email/meeting intent
    has_rev_kw = any(k in msg for k in ["upsell value", "deal value", "revenue opportunity", "revenue from", "opportunity from"])
    has_churn_kw = any(k in msg for k in ["high churn", "high risk", "churn risk", "at risk", "churn"])
    if has_rev_kw and has_churn_kw:
        return "churn_revenue_calc"

    # Custom recommendation + regenerate
    if ("custom recommendation" in msg or "add" in msg) and ("eligible" in msg or "regenerate" in msg or "generate" in msg):
        return "custom_rec_and_regenerate"

    if any(k in msg for k in ["batch", "run for all", "analyze all", "evaluate all",
                               "all customers", "every customer", "for all the customers",
                               "run recommendations for all", "recommendations for all customers"]):
        return "batch_run"

    if "subscribed to" in msg or " but not " in msg or "but don't have" in msg:
        return "subscription_filter"

    if any(k in msg for k in ["should not recommend", "no upsell", "not recommend",
                               "don't recommend", "avoid upsell", "skip upsell"]):
        return "no_upsell_customers"

    if any(k in msg for k in ["using professional", "on professional", "professional plan",
                               "using enterprise", "on enterprise", "enterprise plan",
                               "using starter", "on starter", "starter plan",
                               "using basic", "basic plan", "plan tier", "plan type"]):
        return "filter_by_plan"

    if any(k in msg for k in ["purchased product", "bought product", "recommended product", 
                               "who have product", "with product", "customers recommended",
                               "using the product", "using product", "has product", "have the product"]):
        return "filter_by_recommended_product"

    import re as _re
    # churn_revenue_calc: "revenue opportunity from top N high churn customers" — must come BEFORE highest_revenue
    has_revenue = any(k in msg for k in ["revenue opportunity", "revenue", "opportunity", "deal value", "upsell value"])
    has_churn_ctx = any(k in msg for k in ["high churn", "high risk", "churn", "at risk"])
    has_top_n = bool(_re.search(r'top\s+\d+', msg))
    if has_revenue and has_churn_ctx:
        return "churn_revenue_calc"

    if any(k in msg for k in ["top 5", "top customers", "high confidence", "best recommendations", "top recommendations"]):
        return "top_recommendations"
    if has_top_n and any(k in msg for k in ["recommendation", "recommend"]):
        return "top_recommendations"
    if any(k in msg for k in ["highest revenue", "most revenue", "best opportunity",
                               "highest deal", "highest opportunity", "revenue opportunity"]):
        return "highest_revenue"
    if any(k in msg for k in ["analytics", "summary", "overview", "total revenue", "how many customers",
                               "recommendation distribution", "confidence score", "recommended products"]):
        return "analytics"

    if any(k in msg for k in ["top selling", "top products", "popular product", "best product", "what sells"]):
        return "top_products_by_segment"

    if any(k in msg for k in ["high churn", "high risk", "at-risk", "at risk", "customers at risk"]):
        return "churn_list"
    if any(k in msg for k in ["medium churn", "medium risk", "moderate risk", "moderate churn"]):
        return "medium_risk_list"
    if any(k in msg for k in ["low churn", "low risk", "safe customers", "stable customers"]):
        return "low_risk_list"

    if any(k in msg for k in ["benefit", "rationale", "reason for", "why recommend", "why this"]):
        return "recommendation_benefits"

    if any(k in msg for k in ["catalog", "list of products", "product list", "available products",
                               "what products", "which products"]):
        return "catalog_query"

    if any(k in msg for k in ["weight", "priority", "feature weight"]) \
            and not any(k in msg for k in ["recommend", "upsell for"]):
        return "feature_weights"

    if any(k in msg for k in ["send email", "email recommendation", "email this",
                               "send recommendation", "mail the"]):
        return "send_email"
    if any(k in msg for k in ["schedule", "meeting", "google meet", "calendar",
                               "book a call", "book a meeting"]):
        return "schedule_meeting"

    if any(k in msg for k in ["show me", "look up", "find", "tell me about",
                               "profile of", "who is", "info on"]):
        return "customer_lookup"
    if any(k in msg for k in ["recommend", "suggestion", "upsell for", "upgrade", "cross-sell"]):
        return "recommendation"
    if any(k in msg for k in ["customer", "churn", "risk"]):
        return "customer_lookup"

    return "unknown"


def _classify_intent(message: str) -> str:
    """LLM-first intent classification with keyword fallback."""
    msg = message.lower().strip()
    # Fast path: skip LLM for obvious short small talk
    if len(msg) < 15 and any(msg == k or msg.startswith(k + " ") for k in
                              ["hi", "hello", "hey", "thanks", "bye", "good morning"]):
        return "small_talk"
    
    # Fast path for genuinely multi-step intents the LLM tends to oversimplify
    # into a plain churn/revenue list. Single-filter intents are left to the
    # LLM so weak keywords (e.g. "with product") can't shortcut them.
    keyword_intent = _keyword_classify_intent(message)
    # Prefer instant deterministic routing for recognized intents; save model
    # latency for questions that cannot be classified locally.
    if keyword_intent != "unknown":
        return keyword_intent

    # LLM understands any natural language phrasing
    llm_intent = _llm_classify_intent(message)
    if llm_intent and llm_intent != "unknown":
        return llm_intent
    # Keyword fallback handles LLM failure or timeout
    return keyword_intent


def _get_or_create_session(conversation_id: Optional[str], tenant_id: str):
    if conversation_id and conversation_id in _sessions:
        session = _sessions[conversation_id]
        session["tenant_id"] = tenant_id
        return conversation_id, session
    # Try loading from DB (survives server restarts and logout/login)
    if conversation_id:
        persisted = db.load_chat_session(conversation_id, tenant_id)
        if persisted:
            _sessions[conversation_id] = persisted
            return conversation_id, _sessions[conversation_id]
    cid = conversation_id or str(uuid.uuid4())
    _sessions[cid] = {
        "conversation_id": cid, "tenant_id": tenant_id, "history": [],
        "last_customer_id": None, "last_customer_name": None,
        "created_at": datetime.utcnow().isoformat(),
        "first_message": None,
    }
    return cid, _sessions[cid]


def _add_to_history(session: dict, role: str, content: str):
    session["history"].append({"role": role, "content": content})
    if role == "user" and not session.get("first_message"):
        session["first_message"] = content
    if len(session["history"]) > _MAX_HISTORY:
        session["history"] = session["history"][-_MAX_HISTORY:]
    try:
        db.save_chat_session(session)
    except Exception as e:
        log.warning("Could not persist chat session: %s", e)


def _build_system_prompt(session: dict, tenant_id: str) -> str:
    ctx = ""
    if session.get("last_customer_id"):
        ctx = f" Last customer discussed: {session.get('last_customer_name', session['last_customer_id'])} (ID: {session['last_customer_id']})."
    return (
        f"You are an intelligent sales assistant for the Traject revenue intelligence platform.{ctx}\n"
        f"Help account managers understand customers, identify upsell opportunities, and take action.\n"
        f"FORMATTING RULES — strictly follow these:\n"
        f"- Use only plain text, **bold**, and bullet points (•).\n"
        f"- NEVER use markdown headings (###, ##, #) or horizontal rules (---).\n"
        f"- NEVER add a 'Next Steps', 'Summary', or closing call-to-action section.\n"
        f"- Keep responses short and direct. No long introductions or conclusions.\n"
        f"For small talk, respond naturally in one sentence."
    )


def _call_llm(system: str, history: list, user_message: str, tenant_id: str) -> str:
    client, deployment = _get_indiaai_client()
    if not client:
        return _rule_fallback(user_message)
    messages = [{"role": "system", "content": system}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_message})
    try:
        resp = client.chat.completions.create(
            model=deployment, 
            messages=messages, 
            max_tokens=1024, 
            temperature=0.7,
            timeout=60.0
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error("LLM call failed: %s", e)
        return _rule_fallback(user_message)


def _rule_fallback(message: str) -> str:
    import re
    msg = message.lower()
    if re.search(r'\b(hi|hello|hey)\b', msg):
        return "Hello! I'm Traject's AI assistant. Ask me about customers, recommendations, analytics, or scheduling meetings."
    if "analytics" in msg:
        return "I can pull analytics data for you. Ask me for an overview, churn distribution, or revenue opportunity."
    if "customer" in msg:
        return "I can look up customers. Provide the customer name or ID."
    return "I'm here to help with customers, recommendations, analytics, emails, and meetings!"


def _tokenize(s: str) -> list:
    """Split a string into lowercase word tokens.
    Handles: spaces/punctuation, CamelCase, PascalCase, and common business suffixes.
    'FreeManLLC' -> ['freeman', 'llc']
    'techflow-inc' -> ['techflow', 'inc']
    """
    import re
    # Insert space before each uppercase letter that follows a lowercase (CamelCase split)
    s2 = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
    # Also split on digits-to-letters and letters-to-digits transitions
    s2 = re.sub(r'([a-zA-Z])([0-9])', r'\1 \2', s2)
    s2 = re.sub(r'([0-9])([a-zA-Z])', r'\1 \2', s2)
    return re.findall(r'[a-z0-9]+', s2.lower())


def _name_score(query_tokens: list, candidate_name: str) -> float:
    """Returns a match score 0.0–1.0 between query tokens and a candidate name.
    Any single token that matches any part of the candidate name is a hit.
    Returns the fraction of query tokens that matched."""
    if not query_tokens or not candidate_name:
        return 0.0
    name_lower = candidate_name.lower()
    hits = sum(1 for tok in query_tokens if tok in name_lower)
    return hits / len(query_tokens)


def _fetch_customer(tenant_id: str, query: str):
    customers = db.get_customers(tenant_id)
    q = query.lower().strip()
    # 1. Exact ID match
    for c in customers:
        if c["customer_id"].lower() == q:
            return c, None
    # 2. Exact name match (case-insensitive)
    for c in customers:
        if (c.get("customer_name") or "").lower() == q:
            return c, None
    # 3. Substring match on name
    exact_sub = [c for c in customers if q in (c.get("customer_name") or "").lower()]
    if len(exact_sub) == 1:
        return exact_sub[0], None
    if len(exact_sub) > 1:
        names = ", ".join(m.get("customer_name", m["customer_id"]) for m in exact_sub[:5])
        return None, f"Multiple customers matched: {names}. Please be more specific."
    # 4. Fuzzy token match — split query into words and match each independently
    q_tokens = _tokenize(query)
    # Remove noise words that appear in nearly every name
    stop = {"llc", "inc", "ltd", "co", "the", "and", "or", "of", "for", "group", "corp"}
    meaningful_tokens = [t for t in q_tokens if t not in stop] or q_tokens
    scored = [(c, _name_score(meaningful_tokens, c.get("customer_name") or c["customer_id"])) for c in customers]
    scored.sort(key=lambda x: x[1], reverse=True)
    best_score = scored[0][1] if scored else 0.0
    if best_score >= 0.5:
        top_matches = [s for s in scored if s[1] >= best_score - 0.1]
        if len(top_matches) == 1:
            return top_matches[0][0], None
        if len(top_matches) <= 5:
            names = ", ".join(m[0].get("customer_name", m[0]["customer_id"]) for m in top_matches)
            return None, f"Did you mean one of: {names}?"
    # 5. Partial ID match
    id_matches = [c for c in customers if q in c["customer_id"].lower()]
    if len(id_matches) == 1:
        return id_matches[0], None
    return None, None


def _top_products(customer: dict, rec: dict | None, catalog: list, limit: int = 3, exclude_terms: list = None) -> list:
    """Rank up to `limit` product recommendations with confidence for a customer.

    Slot 1 is the agent's own `recommended_product`; the remaining slots are
    filled from the catalog by tier (mirrors web_api's `all_recommendations`),
    so the chat can always show a "top N" list even for lightly analyzed rows.
    """
    from app.web_api import _stored_confidence
    seats = float(customer.get("seats") or 0)
    owned = [(customer.get("plan_tier") or "").lower(), (customer.get("current_product") or "").lower()]
    products: list = []
    seen: set = set()
    primary_conf = None
    ex_terms = [t.lower() for t in (exclude_terms or []) if t]

    def _is_excluded(prod_name):
        if not prod_name: return True
        n = prod_name.lower()
        # skip if customer already owns it
        if any(n in o for o in owned): return True
        # skip if explicitly excluded by query
        if any(ex in n for ex in ex_terms): return True
        return False

    if rec and rec.get("recommended_product") and not _is_excluded(rec["recommended_product"]):
        primary_conf = _stored_confidence(rec)
        products.append({
            "product": rec["recommended_product"],
            "confidence": primary_conf,
            "deal_value": int(round(rec.get("estimated_deal_value") or 0)),
        })
        seen.add(rec["recommended_product"])
        
        # Only pad with generic catalog items if an actual AI recommendation exists.
        # This prevents generating fake recommendations before batch analysis is run.
        if len(products) < limit and catalog:
            sorted_cat = sorted(catalog, key=lambda x: int(x.get("tier_level", 0) or 0), reverse=True)
            base_conf = primary_conf if primary_conf else 0.6
            for c in sorted_cat:
                if len(products) >= limit:
                    break
                name = c.get("product_name")
                if not name or name in seen or _is_excluded(name):
                    continue
                seen.add(name)
                deal = round(float(c.get("price_per_seat", 0) or 0) * seats * 12)
                products.append({
                    "product": name,
                    "confidence": round(max(0.05, base_conf - 0.12 * len(products)), 2),
                    "deal_value": int(deal),
                })
        
    return products


def _build_customer_summary(tenant_id: str, customer: dict) -> tuple:
    from app.web_api import _adoption_pct, _churn, _catalog_index
    catalog = db.get_product_catalog(tenant_id)
    cat_index = _catalog_index(catalog)
    usage = db.get_usage(tenant_id, customer["customer_id"])
    tickets = db.get_tickets(tenant_id, customer["customer_id"])
    adoption = _adoption_pct(customer, usage)
    score, risk, _, _, renewal_days = _churn(customer, usage, tickets, adoption)
    recs = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
    rec = recs.get(customer["customer_id"])
    current_product = customer.get("current_product") or customer.get("plan_tier") or "Unknown"
    plan = customer.get("plan_tier") or ""
    
    # Reconcile risk: use LLM-assessed risk if available, else fallback to local math
    display_risk = (rec.get("churn_risk") if rec and rec.get("churn_risk") else risk).upper()
    
    lines = [
        f"**{customer.get('customer_name')}** (ID: {customer['customer_id']})",
        f"Current product: **{current_product}**" + (f" | Plan: {plan}" if plan and plan.lower() != current_product.lower() else ""),
        f"Churn: **{display_risk}** | Renewal in {renewal_days} days",
        f"Adoption: {adoption}% | Open tickets: {len([t for t in tickets if not t.get('resolved')])}",
    ]
    top = _top_products(customer, rec, catalog, limit=3)
    if top:
        lines.append("")
        label = f"**Top {len(top)} product recommendations:**" if len(top) > 1 else "**Top product recommendation:**"
        lines.append(label)
        for i, p in enumerate(top, 1):
            conf = int((p["confidence"] or 0) * 100)
            lines.append(f"  • **{i}. {p['product']}** — {conf}% confidence")
            prod_detail = cat_index.get(p["product"])
            if prod_detail:
                features_raw = prod_detail.get("features") or ""
                features = [f.strip() for f in features_raw.split("|") if f.strip()]
                for feat in features[:4]:
                    lines.append(f"    → {feat}")
    else:
        lines.append("No recommendation yet — run Analysis on this customer.")
    data = {
        "customer_id": customer["customer_id"],
        "customer_name": customer.get("customer_name"),
        "plan_tier": customer.get("plan_tier"),
        "churn_risk": display_risk,
        "churn_score": score,
        "renewal_days": renewal_days,
        "adoption": adoption,
        "recommended_product": (top[0]["product"] if top else None),
        "confidence": (top[0]["confidence"] if top else None),
        "top_products": top,
    }
    return "\n".join(lines), data


def _analytics_summary(tenant_id: str) -> tuple:
    customers = db.get_customers(tenant_id)
    recs = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
    analyzed = [c for c in customers if c["customer_id"] in recs]
    with_rec = [c for c in analyzed if recs[c["customer_id"]].get("recommended_product")]
    high = [c for c in analyzed if (recs[c["customer_id"]].get("churn_risk") or "").upper() == "HIGH"]
    opp = sum(int(recs[c["customer_id"]].get("estimated_deal_value") or 0) for c in with_rec)
    text = (
        f"**Analytics Summary**\n"
        f"- Total customers: {len(customers)}\n"
        f"- Analyzed: {len(analyzed)}\n"
        f"- With recommendations: {len(with_rec)}\n"
        f"- High churn risk: {len(high)}\n"
        f"- Total opportunity: **${opp:,}**"
    )
    data = {"total_customers": len(customers), "analyzed": len(analyzed),
            "with_recommendations": len(with_rec), "high_risk": len(high), "total_opportunity": opp}
    return text, data


def process_message(
    message: str,
    tenant_id: str,
    conversation_id: Optional[str] = None,
    hint_customer_id: Optional[str] = None,
) -> dict:
    cid, session = _get_or_create_session(conversation_id, tenant_id)
    intent = _classify_intent(message)
    log.info("[chat:%s] intent=%s", cid[:8], intent)

    customer_data = None
    analytics_data = None
    actions = []
    reply = ""

    if intent == "small_talk":
        reply = _call_llm(_build_system_prompt(session, tenant_id), session["history"], message, tenant_id)

    elif intent == "analytics":
        try:
            from collections import Counter
            customers = db.get_customers(tenant_id)
            recs_list = db.get_latest_recommendations(tenant_id)
            recs = {r["customer_id"]: r for r in recs_list}
            analyzed = [c for c in customers if c["customer_id"] in recs]
            with_rec = [c for c in analyzed if recs[c["customer_id"]].get("recommended_product")]
            high  = [c for c in analyzed if (recs[c["customer_id"]].get("churn_risk") or "").upper() == "HIGH"]
            med   = [c for c in analyzed if (recs[c["customer_id"]].get("churn_risk") or "").upper() == "MEDIUM"]
            low   = [c for c in analyzed if (recs[c["customer_id"]].get("churn_risk") or "").upper() == "LOW"]
            opp   = sum(int(recs[c["customer_id"]].get("estimated_deal_value") or 0) for c in with_rec)

            lines = [
                "**📊 Recommendation Analytics**\n",
                "**Overview:**",
                f"  • Total customers: **{len(customers)}**",
                f"  • Analyzed: **{len(analyzed)}**",
                f"  • With recommendations: **{len(with_rec)}**",
                f"  • Total revenue opportunity: **${opp:,}**",
                "",
                "**🔥 Churn Risk Distribution:**",
                f"  • 🔴 High risk: **{len(high)}** customers",
                f"  • 🟡 Medium risk: **{len(med)}** customers",
                f"  • 🟢 Low risk: **{len(low)}** customers",
            ]

            # Product distribution with confidence scores
            recs_with_product = [r for r in recs_list if r.get("recommended_product")]
            counts = Counter(r["recommended_product"] for r in recs_with_product)
            if counts:
                lines.append("")
                lines.append("**🎯 Recommendation Distribution (by product):**")
                for product, count in counts.most_common():
                    same = [r for r in recs_with_product if r.get("recommended_product") == product]
                    avg_conf = int(sum((r.get("confidence") or 0) for r in same) / len(same) * 100)
                    total_val = sum(int(r.get("estimated_deal_value") or 0) for r in same)
                    pct = int(count / len(recs_with_product) * 100)
                    lines.append(f"  • **{product}**")
                    lines.append(f"    → {count} customers ({pct}%) · Avg confidence: **{avg_conf}%** · Opportunity: **${total_val:,}**")

            # Top 3 by confidence
            top_conf = sorted(recs_with_product, key=lambda r: r.get("confidence") or 0, reverse=True)[:3]
            if top_conf:
                lines.append("")
                lines.append("**🏆 Top 3 Customers by Confidence Score:**")
                for i, r in enumerate(top_conf, 1):
                    conf = int((r.get("confidence") or 0) * 100)
                    lines.append(f"  {i}. **{r.get('customer_name', r['customer_id'])}** — {r.get('recommended_product')} ({conf}% confidence)")

            reply = "\n".join(lines)
            analytics_data = {"total_customers": len(customers), "analyzed": len(analyzed),
                              "with_recommendations": len(with_rec), "high_risk": len(high), "total_opportunity": opp}
        except Exception as e:
            reply = f"I couldn't load analytics right now ({e}). Try the Dashboard page."

    elif intent in ("customer_lookup", "recommendation", "send_email", "schedule_meeting", "recommendation_benefits"):
        customer = None
        target_cid = hint_customer_id  # start with explicit hint only

        # Always try to extract the customer name from the current message first.
        # Only fall back to last_customer_id when the message contains no name.
        client, deployment = _get_indiaai_client()
        extracted = "NONE"
        if client and __import__("os").getenv("INDIAAI_LLM_NAME_EXTRACTION", "0") == "1":
            try:
                r = client.chat.completions.create(
                    model=deployment,
                    messages=[{"role": "user", "content": f"Extract ONLY the customer name or ID from: '{message}'. Reply with just the name/ID or 'NONE'."}],
                    max_tokens=160, temperature=0,
                    timeout=25.0
                )
                extracted = r.choices[0].message.content.strip()
            except Exception:
                pass
        if extracted and extracted.upper() != "NONE":
            customer, err = _fetch_customer(tenant_id, extracted)
            if not customer and err:
                reply = err
                _add_to_history(session, "user", message)
                _add_to_history(session, "assistant", reply)
                return {"conversation_id": cid, "reply": reply, "intent": intent, "customer_data": None, "analytics_data": None, "actions": []}
            if customer:
                target_cid = customer["customer_id"]
        if not target_cid:
            skip = {"tell", "me", "the", "a", "an", "show", "get", "find", "look",
                    "up", "of", "for", "about", "what", "is", "are", "give",
                    "recommendation", "recommendations", "recommend", "profile",
                    "detail", "details", "churn", "risk", "analytics", "summary",
                    "schedule", "meeting", "google", "meet", "send", "email",
                    "their", "his", "her", "its", "our", "your", "with", "and",
                    "customer", "products", "top", "confidence", "scores"}
            words = message.split()
            for word in words:
                clean = word.strip("?.,!'\";:")
                if clean.lower() in skip or len(clean) < 3:
                    continue
                c_try, e_try = _fetch_customer(tenant_id, clean)
                if c_try:
                    customer = c_try
                    target_cid = c_try["customer_id"]
                    break
        # Fall back to last discussed customer only if no name found in message
        if not target_cid:
            target_cid = session.get("last_customer_id")

        if target_cid and not customer:
            rows = db.get_customers(tenant_id, [target_cid])
            customer = rows[0] if rows else None
        if customer:
            session["last_customer_id"] = customer["customer_id"]
            session["last_customer_name"] = customer.get("customer_name")
            if intent in ("customer_lookup", "recommendation"):
                base, customer_data = _build_customer_summary(tenant_id, customer)
                sys_prompt = _build_system_prompt(session, tenant_id)
                llm_reply = _call_llm(sys_prompt, session["history"],
                    f"User asked: {message}\n\nCustomer data:\n{base}\n\n"
                    f"Reply using ONLY bullet points and bold text. No headings, no horizontal rules, no Next Steps section.",
                    tenant_id)
                generic_fallbacks = {
                    "I can look up customers", "I'm here to help", "I can pull analytics",
                    "I'm your AI Sales Assistant", "Ask me about customers",
                }
                if any(fb in llm_reply for fb in generic_fallbacks):
                    reply = base
                else:
                    reply = llm_reply
                actions = []
            elif intent == "recommendation_benefits":
                recs = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
                rec = recs.get(customer["customer_id"])
                if rec and rec.get("rationale"):
                    # Detect if they asked about a different product
                    catalog = db.get_product_catalog(tenant_id)
                    asked_prod = None
                    for p in catalog:
                        name = p.get("product_name", "")
                        if name and name.lower() in message.lower():
                            asked_prod = name
                            break
                    
                    prefix = ""
                    actual_prod = rec.get("recommended_product")
                    if asked_prod and actual_prod and asked_prod.lower() != actual_prod.lower():
                        prefix = f"💡 **Note:** You asked about **{asked_prod}**, but my top recommendation for this customer is **{actual_prod}**.\n\n"

                    reply = (
                        prefix +
                        f"**Benefits & Rationale for {customer.get('customer_name', customer['customer_id'])}:**\n\n"
                        f"**Recommended Product:** {actual_prod}\n\n"
                        f"**Why this is a good fit:**\n{rec.get('rationale')}\n\n"
                        f"**Churn Risk:** {rec.get('churn_risk')}\n"
                        f"**Risk Factor:**\n{rec.get('churn_reason', 'N/A')}"
                    )
                    _, customer_data = _build_customer_summary(tenant_id, customer)
                else:
                    reply = f"I don't have a specific recommendation rationale for **{customer.get('customer_name', customer['customer_id'])}** yet. Run analysis first."
                    actions = [{"type": "go_to_batch", "label": "Run batch analysis"}]
            elif intent == "send_email":
                base, customer_data = _build_customer_summary(tenant_id, customer)
                reply = base + (
                    f"\n\nReady to email these recommendations to **{customer.get('customer_name')}**."
                )
                actions = []
            elif intent == "schedule_meeting":
                base, customer_data = _build_customer_summary(tenant_id, customer)
                reply = base + (
                    f"\n\nReady to schedule a meeting with **{customer.get('customer_name')}**."
                )
                actions = []
        else:
            # No specific customer identified — give a helpful contextual answer via LLM
            # rather than a confusing "I couldn't find that customer" for general questions.
            sys_prompt = _build_system_prompt(session, tenant_id)
            llm_reply = _call_llm(sys_prompt, session["history"], message, tenant_id)
            generic_fallbacks = {"I can look up customers", "I'm here to help", "I can pull analytics",
                                  "Provide their name or ID"}
            if any(fb in llm_reply for fb in generic_fallbacks) or not llm_reply:
                reply = (
                    "I couldn't identify a specific customer in your query. "
                    "Try asking like:\n"
                    "- **'Show me Toy Planet'** — for a specific customer\n"
                    "- **'List all high churn risk customers'** — for a risk list\n"
                    "- **'Customers on Enterprise plan'** — to filter by plan\n"
                    "- **'Who is recommended FBA Inventory Optimization'** — to filter by product"
                )
            else:
                reply = llm_reply
            actions = [{"type": "go_to_customers", "label": "Browse customers"}]

    elif intent == "top_recommendations":
        try:
            import re
            msg_lower = message.lower()

            # Detect an explicit confidence THRESHOLD ("above/over/greater than
            # 80%", "at least 80%", ">80%") as opposed to a plain "top N" count.
            # Both phrasings contain a bare number, so without this check
            # "confidence above 80%" was being read as "top 80" (a count) and
            # sliced unfiltered instead of being filtered to confidence > 80.
            threshold_match = re.search(
                r'(?:confidence\w*\s*(?:score[s]?)?\s*)?'
                r'(?:above|over|greater than|higher than|more than|at least|>=?)\s*(\d+)\s*%',
                msg_lower
            )
            confidence_threshold = int(threshold_match.group(1)) if threshold_match else None

            # Pull remaining digits (for plain "top N" requests) from the
            # message with the threshold's own number removed, so it can't
            # be mistaken for a count too.
            nums_source = msg_lower
            if threshold_match:
                nums_source = msg_lower[:threshold_match.start(1)] + msg_lower[threshold_match.end(1):]
            nums = [int(n) for n in re.findall(r'\d+', nums_source)]

            # Parse intent:
            # "Show 3 recommendations for last 5 customers"  -> recs_per_customer=3, customer_count=5
            # "Top 5 recommendations" -> top_n=5 (flat list)
            # "confidence above 80%" -> confidence_threshold=80 (filter, not count)
            has_last = "last" in msg_lower
            catalog = db.get_product_catalog(tenant_id)
            recs = db.get_latest_recommendations(tenant_id)
            cust_map = {c["customer_id"]: c for c in db.get_customers(tenant_id)}

            if confidence_threshold is not None:
                # Filter by confidence threshold instead of slicing a top-N count.
                with_rec = [r for r in recs if r.get("recommended_product") and r.get("confidence")]
                selected_recs = [r for r in with_rec if (r.get("confidence") or 0) * 100 > confidence_threshold]
                selected_recs.sort(key=lambda x: x.get("confidence") or 0, reverse=True)
                want_customer_view = "customers" in msg_lower
                if selected_recs:
                    if want_customer_view:
                        lines = [f"**Customers with recommendation confidence above {confidence_threshold}%:** ({len(selected_recs)})\n"]
                        for r in selected_recs:
                            cust = cust_map.get(r["customer_id"], {})
                            lines.append(f"• **{r.get('customer_name', r['customer_id'])}**")
                            top = _top_products(cust, r, catalog, limit=3)
                            for i, p in enumerate(top, 1):
                                conf = int((p["confidence"] or 0) * 100)
                                lines.append(f"  → {i}. {p['product']} ({conf}% confidence)")
                    else:
                        lines = [f"**Recommendations with confidence above {confidence_threshold}%:** ({len(selected_recs)})\n"]
                        for i, r in enumerate(selected_recs, 1):
                            conf = int(r.get("confidence", 0) * 100)
                            deal = int(r.get("estimated_deal_value") or 0)
                            lines.append(f"{i}. **{r.get('customer_name', r['customer_id'])}**")
                            lines.append(f"   • Recommended: **{r.get('recommended_product')}** ({conf}% confidence)")
                            lines.append(f"   • Value: ${deal:,} | Risk: {r.get('churn_risk', 'Unknown')}")
                    reply = "\n".join(lines)
                    actions = [{"type": "go_to_batch", "label": "View all recommendations"}]
                else:
                    reply = f"No customers have a recommendation with confidence above {confidence_threshold}%."
                    actions = [{"type": "go_to_batch", "label": "Run batch analysis"}]
            elif has_last and len(nums) >= 2:
                recs_per_customer = nums[0]  # e.g. 3
                customer_count = nums[1]     # e.g. 5

                # Get last N customers by insertion order
                recs_with_data = [r for r in recs if r.get("customer_id")]
                recs_with_data.sort(key=lambda x: str(x.get("customer_id", "")), reverse=True)
                selected_recs = recs_with_data[:customer_count]

                if selected_recs:
                    lines = [f"**Top {recs_per_customer} Recommendations for last {customer_count} customers:**\n"]
                    for r in selected_recs:
                        cust = cust_map.get(r["customer_id"], {})
                        lines.append(f"• **{r.get('customer_name', r['customer_id'])}**")
                        top = _top_products(cust, r, catalog, limit=recs_per_customer)
                        for i, p in enumerate(top, 1):
                            conf = int((p["confidence"] or 0) * 100)
                            lines.append(f"  → {i}. {p['product']} ({conf}% confidence)")
                    reply = "\n".join(lines)
                    actions = [{"type": "go_to_batch", "label": "View all recommendations"}]
                else:
                    reply = "No recommendations found yet. Run batch analysis to generate some."
                    actions = [{"type": "go_to_batch", "label": "Run batch analysis"}]
            elif "customers" in msg_lower:
                # Format as top N customers and their recommendations
                top_n = nums[0] if nums else 5
                with_rec = [r for r in recs if r.get("recommended_product") and r.get("confidence")]
                with_rec.sort(key=lambda x: x.get("confidence") or 0, reverse=True)
                selected_recs = with_rec[:top_n]
                if selected_recs:
                    lines = [f"**Top {top_n} Customers and their Recommendations:**\n"]
                    for r in selected_recs:
                        cust = cust_map.get(r["customer_id"], {})
                        lines.append(f"• **{r.get('customer_name', r['customer_id'])}**")
                        top = _top_products(cust, r, catalog, limit=3)
                        for i, p in enumerate(top, 1):
                            conf = int((p["confidence"] or 0) * 100)
                            lines.append(f"  → {i}. {p['product']} ({conf}% confidence)")
                    reply = "\n".join(lines)
                    actions = [{"type": "go_to_batch", "label": "View all recommendations"}]
                else:
                    reply = "No recommendations found yet. Run batch analysis to generate some."
                    actions = [{"type": "go_to_batch", "label": "Run batch analysis"}]
            else:
                # Flat top N list by confidence
                top_n = nums[0] if nums else 5
                with_rec = [r for r in recs if r.get("recommended_product") and r.get("confidence")]
                with_rec.sort(key=lambda x: x.get("confidence") or 0, reverse=True)
                top_recs = with_rec[:top_n]
                if top_recs:
                    lines = [f"**Top {top_n} Recommendations (by confidence score):**\n"]
                    for i, r in enumerate(top_recs, 1):
                        conf = int(r.get("confidence", 0) * 100)
                        deal = int(r.get("estimated_deal_value") or 0)
                        lines.append(f"{i}. **{r.get('customer_name', r['customer_id'])}**")
                        lines.append(f"   • Recommended: **{r.get('recommended_product')}** ({conf}% confidence)")
                        lines.append(f"   • Value: ${deal:,} | Risk: {r.get('churn_risk', 'Unknown')}")
                    reply = "\n".join(lines)
                    actions = [{"type": "go_to_batch", "label": "View all recommendations"}]
                else:
                    reply = "No recommendations found yet. Run batch analysis to generate some."
                    actions = [{"type": "go_to_batch", "label": "Run batch analysis"}]
        except Exception as e:
            reply = f"Couldn't load top recommendations: {e}"

    elif intent == "highest_revenue":
        try:
            import re as _re
            n_match = _re.search(r'(?:top|best)\s+(\d+)', message, _re.I)
            top_n = int(n_match.group(1)) if n_match else None
            
            recs = db.get_latest_recommendations(tenant_id)
            with_val = [r for r in recs if (r.get("estimated_deal_value") or 0) > 0]
            if with_val:
                with_val.sort(key=lambda r: r.get("estimated_deal_value") or 0, reverse=True)
                
                # If they ask for "top N" or use plural "customers", return a list
                if top_n or "customers" in message.lower():
                    import re as _re2
                    limit = top_n or 5
                    selected = with_val[:limit]
                    
                    # Detect if user wants X recommendations per customer e.g. "with 3 recommendations"
                    recs_match = _re2.search(r'with\s+(\d+)\s+rec', message, _re2.I)
                    recs_per = int(recs_match.group(1)) if recs_match else None
                    
                    catalog = db.get_product_catalog(tenant_id)
                    cust_map = {c["customer_id"]: c for c in db.get_customers(tenant_id)}
                    
                    lines = [f"**Top {len(selected)} Customers by Revenue Opportunity:**\n"]
                    for i, r in enumerate(selected, 1):
                        deal = int(r.get("estimated_deal_value") or 0)
                        conf = int((r.get("confidence") or 0) * 100)
                        risk = (r.get("churn_risk") or "Unknown").upper()
                        lines.append(f"{i}. **{r.get('customer_name', r['customer_id'])}** — Risk: {risk}")
                        
                        if recs_per:
                            # Show top N products per customer
                            cust = cust_map.get(r["customer_id"], {})
                            top = _top_products(cust, r, catalog, limit=recs_per)
                            if top:
                                for j, p in enumerate(top, 1):
                                    pconf = int((p["confidence"] or 0) * 100)
                                    pdeal = int(p["deal_value"] or 0)
                                    lines.append(f"   {j}. **{p['product']}** — {pconf}% confidence · ${pdeal:,}")
                        else:
                            lines.append(f"   • Recommended: **{r.get('recommended_product')}** ({conf}% confidence) · Value: **${deal:,}**")
                    reply = "\n".join(lines)
                    actions = [{"type": "go_to_batch", "label": "View all recommendations"}]
                else:
                    # Single best customer logic
                    best = with_val[0]
                    deal = int(best.get("estimated_deal_value") or 0)
                    conf = int((best.get("confidence") or 0) * 100)
                    
                    # Fetch full customer to get plan_tier and calculate renewal_days
                    customers = db.get_customers(tenant_id)
                    cust = next((c for c in customers if c["customer_id"] == best["customer_id"]), {})
                    
                    from app.web_api import _churn, _adoption_pct
                    usage = db.get_usage(tenant_id, best["customer_id"])
                    tickets = db.get_tickets(tenant_id, best["customer_id"])
                    adoption = _adoption_pct(cust, usage) if cust else 0
                    _, _, _, _, renewal_days = _churn(cust, usage, tickets, adoption) if cust else (0, "LOW", "", "", 0)

                    reply = (
                        f"The customer with the **highest revenue opportunity** is:\n\n"
                        f"**{best.get('customer_name', best['customer_id'])}** (ID: `{best['customer_id']}`)"
                        f"\n- Recommended product: **{best.get('recommended_product', 'N/A')}**"
                        f"\n- Deal value: **${deal:,}**"
                        f"\n- Confidence: **{conf}%**"
                        f"\n- Churn risk: **{best.get('churn_risk', 'Unknown')}**"
                    )
                    customer_data = {
                        "customer_id": best["customer_id"],
                        "customer_name": best.get("customer_name"),
                        "recommended_product": best.get("recommended_product"),
                        "estimated_deal_value": deal,
                        "confidence": best.get("confidence"),
                        "churn_risk": best.get("churn_risk"),
                        "plan_tier": cust.get("plan_tier", "Unknown"),
                        "renewal_days": renewal_days,
                    }
                    session["last_customer_id"] = best["customer_id"]
                    session["last_customer_name"] = best.get("customer_name")
                    actions = [
                        {"type": "view_customer", "label": "View full profile", "customer_id": best["customer_id"]},
                    ]
            else:
                reply = "No analyzed customers found yet. Run the batch analysis first."
                actions = [{"type": "go_to_batch", "label": "Go to Batch Evaluate"}]
        except Exception as e:
            reply = f"Couldn't load revenue data: {e}"

    elif intent == "churn_revenue_calc":
        try:
            import re as _re
            recs = db.get_latest_recommendations(tenant_id)
            # Extract N from query (e.g. "top 6")
            n_match = _re.search(r'top\s+(\d+)', message, _re.I)
            top_n = int(n_match.group(1)) if n_match else None

            # Determine risk tier from query
            msg_lower = message.lower()
            if "medium" in msg_lower:
                risk_tier = "MEDIUM"
                tier_label = "MEDIUM"
            elif "low" in msg_lower:
                risk_tier = "LOW"
                tier_label = "LOW"
            else:
                risk_tier = "HIGH"
                tier_label = "HIGH"

            filtered = [
                r for r in recs
                if (r.get("churn_risk") or "").upper() == risk_tier
                and (r.get("estimated_deal_value") or 0) > 0
            ]
            filtered.sort(key=lambda r: r.get("estimated_deal_value") or 0, reverse=True)

            if top_n:
                selected = filtered[:top_n]
                label = f"Top {top_n} {tier_label} churn risk customers"
            else:
                selected = filtered
                label = f"All {tier_label} churn risk customers"

            if selected:
                total_opp = sum(int(r.get("estimated_deal_value") or 0) for r in selected)
                lines = [f"**💰 Revenue Opportunity — {label}:**\n"]
                for i, r in enumerate(selected, 1):
                    deal = int(r.get("estimated_deal_value") or 0)
                    conf = int((r.get("confidence") or 0) * 100)
                    lines.append(f"  {i}. **{r.get('customer_name', r['customer_id'])}**")
                    lines.append(f"     → {r.get('recommended_product', 'N/A')} ({conf}% confidence) · **${deal:,}**")
                lines.append(f"\n**📊 Total Revenue Opportunity: ${total_opp:,}**")
                reply = "\n".join(lines)
            else:
                reply = f"No {tier_label} churn risk customers with deal values found. Run batch analysis first."
            actions = [{"type": "go_to_customers", "label": "View all customers"}]
        except Exception as e:
            reply = f"Couldn't calculate churn revenue: {e}"

    elif intent == "no_upsell_customers":
        try:
            recs = db.get_latest_recommendations(tenant_id)
            no_upsell = [r for r in recs if not r.get("recommended_product") or
                         r.get("no_recommendation_reason_code") in ("signal_rejected", "critic_vetoed", "no_opportunity_found")]
            if no_upsell:
                lines = [f"**Customers NOT recommended for upselling ({len(no_upsell)}):**\n"]
                for r in no_upsell:
                    deal = int(r.get("estimated_deal_value") or 0)
                    risk = r.get("churn_risk", "Unknown")
                    reason = r.get("churn_reason") or r.get("rationale") or "No strong upsell signal"
                    lines.append(f"  • **{r.get('customer_name', r['customer_id'])}** — Risk: {risk}")
                    lines.append(f"    Reason: {reason}")
                reply = "\n".join(lines)
            else:
                reply = "All analyzed customers currently have an upsell recommendation. Run batch analysis to refresh."
            actions = [{"type": "go_to_batch", "label": "Run batch analysis"}]
        except Exception as e:
            reply = f"Couldn't load data: {e}"

    elif intent == "subscription_filter":
        try:
            import re
            recs_map = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
            catalog = db.get_product_catalog(tenant_id)
            customers = db.get_customers(tenant_id)
            a = b = None
            am = re.search(r"subscrib\w*\s+(?:to\s+)?(.+?)(?:\s+but not\b|\s+but don'?t have\b|\s+but without\b|\s+without\b|[,.?]|$)", message, re.I)
            if not am:
                # Fallback for phrasing that skips "subscribed" entirely,
                # e.g. "customers currently on X", "who has X" — still a
                # single-product membership question, just worded differently.
                am = re.search(r"(?:currently on|who has|who have|customers with)\s+(.+?)(?:\s+but not\b|\s+but don'?t have\b|\s+but without\b|\s+without\b|[,.?]|$)", message, re.I)
            if am:
                a = am.group(1).strip(" .,'\"?")
            bm = re.search(r"(?:but not|but don'?t have|but without|without|don'?t have)\s+(.+?)(?:[,.?]|\s+and generate|\s+and\b|$)", message, re.I)
            if bm:
                b = bm.group(1).strip(" .,'\"?")

            def _owns(c: dict, term: str) -> bool:
                if not term:
                    return False
                hay = " ".join(str(c.get(k) or "") for k in ("plan_tier", "current_product")).lower()
                return term.lower() in hay

            matched = [c for c in customers if (not a or _owns(c, a)) and (not b or not _owns(c, b))]
            if a and matched:
                title = f"Customers subscribed to **{a}**" + (f" but not **{b}**" if b else "")
                lines = [f"{title} ({len(matched)}):\n"]
                for c in matched[:25]:
                    rec = recs_map.get(c["customer_id"])
                    # Exclude BOTH a (already subscribed) and b (the one they don't have — obvious upsell, skip it in general recs)
                    top = _top_products(c, rec, catalog, limit=3, exclude_terms=[a, b])
                    lines.append(f"  • **{c.get('customer_name', c['customer_id'])}**")
                    if top:
                        label = f"    - **Top {len(top)} Recommendations:**" if len(top) > 1 else "    - **Recommendation:**"
                        lines.append(label)
                    for i, p in enumerate(top, 1):
                        conf = int((p["confidence"] or 0) * 100)
                        lines.append(f"    → {i}. {p['product']} ({conf}% confidence)")
                reply = "\n".join(lines)
                actions = [{"type": "go_to_customers", "label": "View all customers"}]
            else:
                catalog_names = ", ".join(p.get("product_name", "") for p in catalog[:6]) or "your catalog"
                reply = (
                    f"I couldn't find customers subscribed to **{a or 'that product'}**"
                    + (f" (and not **{b}**)" if b else "")
                    + f" in this tenant's data. The products in your catalog are: {catalog_names}.\n\n"
                    "Try a subscription name from your own catalog, or ask **'Customers on Enterprise plan'**."
                )
                actions = [{"type": "go_to_customers", "label": "Browse customers"}]
        except Exception as e:
            reply = f"Couldn't apply the subscription filter: {e}"

    elif intent == "filter_by_plan":
        try:
            import re
            msg_lower = message.lower()
            # Extract plan tier from message with word boundaries
            plan_map = {
                "enterprise": "enterprise",
                "professional": "professional",
                "starter": "starter",
                "basic": "basic",
                "pro": "professional",
            }
            matched_plan = None
            for k, v in plan_map.items():
                if re.search(r'\b' + re.escape(k) + r'\b', msg_lower):
                    matched_plan = v
                    break

            customers = db.get_customers(tenant_id)
            unique_plans = sorted(list(set(c.get("plan_tier") for c in customers if c.get("plan_tier"))))
            for p in unique_plans:
                plan_map[p.lower()] = p.lower()

            matched_plan = None
            for k, v in plan_map.items():
                if re.search(r'\b' + re.escape(k) + r'\b', msg_lower):
                    matched_plan = v
                    break

            recs = {r["customer_id"]: r for r in db.get_latest_recommendations(tenant_id)}
            filtered = [
                c for c in customers
                if (c.get("plan_tier") or "").lower() == matched_plan
            ] if matched_plan else customers
            
            if filtered and matched_plan:
                plan_label = f'"{matched_plan.title()}"' if matched_plan else "all"
                lines = [f"**Customers on {plan_label} plan ({len(filtered)}):**\n"]
                for c in filtered:
                    rec = recs.get(c["customer_id"])
                    rec_product = rec.get("recommended_product") if rec else None
                    conf = int((rec.get("confidence") or 0) * 100) if rec else 0
                    risk = (rec.get("churn_risk") or "Unknown") if rec else "Not analyzed"
                    lines.append(f"  • **{c.get('customer_name', c['customer_id'])}** — Risk: {risk}")
                    if rec_product:
                        lines.append(f"    → Recommended: {rec_product} ({conf}% confidence)")
                    else:
                        lines.append(f"    → No recommendation yet")
                reply = "\n".join(lines)
            else:
                plan_label = matched_plan.title() if matched_plan else "that"
                available_plans = ", ".join(unique_plans) if unique_plans else "None"
                reply = f"No customers found on the **{plan_label}** plan.\n\n*Hint: The plans available in this dataset are: {available_plans}*"
            actions = [{"type": "go_to_customers", "label": "View all customers"}]
        except Exception as e:
            reply = f"Couldn't filter by plan: {e}"

    elif intent == "filter_by_recommended_product":
        try:
            msg_lower = message.lower()
            catalog = db.get_product_catalog(tenant_id)
            recs = db.get_latest_recommendations(tenant_id)
            customers = db.get_customers(tenant_id)
            recs_map = {r["customer_id"]: r for r in recs}

            # Dynamically match against the catalog
            matched_product = None
            for p in catalog:
                name = p.get("product_name", "")
                if name and name.lower() in msg_lower:
                    matched_product = name
                    break

            # "recommended for X" and "subscribed to / using / have X" are two
            # different questions — only show the section(s) actually asked
            # about instead of always dumping both, which is what made the
            # previous output confusing for a query that only asked for
            # recommended customers.
            wants_recommended = any(k in msg_lower for k in ["recommend", "suggested", "suggestion"])
            wants_subscribers = any(k in msg_lower for k in [
                "subscribed", "subscriber", "using the product", "using product",
                "currently on", "have the product", "has the product",
                "bought", "purchased", "current product"])
            # If the query gives no clear signal either way, show both (the
            # old default) rather than guessing wrong.
            show_subscribers = wants_subscribers or not (wants_recommended or wants_subscribers)
            show_recommended = wants_recommended or not (wants_recommended or wants_subscribers)

            lines = []

            # Section 1: Current subscribers (current_product field)
            if show_subscribers and matched_product:
                subscribers = [
                    c for c in customers
                    if matched_product.lower() in (c.get("current_product") or "").lower()
                ]
                if subscribers:
                    lines.append(f"**📦 Current subscribers of '{matched_product}' ({len(subscribers)}):**\n")
                    for c in subscribers:
                        rec = recs_map.get(c["customer_id"])
                        risk = (rec.get("churn_risk") if rec else "Unknown").upper() if rec else "Not analyzed"
                        deal = int(rec.get("estimated_deal_value") or 0) if rec else 0
                        lines.append(f"• **{c.get('customer_name', c['customer_id'])}** — Risk: {risk} | Value: ${deal:,}")
                else:
                    lines.append(f"**📦 Current subscribers of '{matched_product}':** None in database\n")
                if show_recommended:
                    lines.append("")

            # Section 2: Customers recommended this product
            if show_recommended:
                filtered = [
                    r for r in recs
                    if matched_product and matched_product.lower() in (r.get("recommended_product") or "").lower()
                ] if matched_product else [r for r in recs if r.get("recommended_product")]

                if filtered:
                    filtered.sort(key=lambda x: x.get("confidence") or 0, reverse=True)
                    lines.append(f"**🎯 Customers recommended '{matched_product or 'any product'}' ({len(filtered)}):**\n")
                    for r in filtered:
                        conf = int((r.get("confidence") or 0) * 100)
                        risk = (r.get("churn_risk") or "Unknown").upper()
                        deal = int(r.get("estimated_deal_value") or 0)
                        if matched_product:
                            lines.append(f"• **{r.get('customer_name', r['customer_id'])}**")
                            lines.append(f"  → Confidence: **{conf}%** | Risk: {risk} | Value: ${deal:,}")
                        else:
                            lines.append(f"• **{r.get('customer_name', r['customer_id'])}** — {r.get('recommended_product')}")
                            lines.append(f"  → Confidence: **{conf}%** | Risk: {risk} | Value: ${deal:,}")
                else:
                    lines.append(f"**🎯 Customers recommended '{matched_product or 'any product'}':** None currently. Run batch analysis to refresh.")

            reply = "\n".join(lines) if lines else f"No data found for **{matched_product}**."
            actions = [{"type": "go_to_customers", "label": "View all customers"}]
        except Exception as e:
            reply = f"Couldn't filter by product: {e}"

    elif intent == "medium_risk_list":
        try:
            import re as _re
            recs = db.get_latest_recommendations(tenant_id)
            catalog = db.get_product_catalog(tenant_id)
            cust_map = {c["customer_id"]: c for c in db.get_customers(tenant_id)}
            medium = [r for r in recs if (r.get("churn_risk") or "").upper() == "MEDIUM"]
            # Parse optional count limit: "top 3", "last three", etc. — skip "top 3 products" (that's per-customer)
            _word_nums = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}
            _lm = _re.search(r'\b(top|last|first|latest)\s+(\d+|one|two|three|four|five|ten)\b(?!\s+products?)', message.lower())
            if _lm:
                _n_raw = _lm.group(2)
                _n = _word_nums.get(_n_raw, int(_n_raw) if _n_raw.isdigit() else None)
                if _n:
                    medium = medium[-_n:] if "last" in _lm.group(1) else medium[:_n]
            if medium:
                lines = [f"🟡 **MEDIUM Churn Risk Customers ({len(medium)}):**\n"]
                for r in medium:
                    cust = cust_map.get(r["customer_id"], {})
                    lines.append(f"  • **{r.get('customer_name', r['customer_id'])}**")
                    top = _top_products(cust, r, catalog, limit=3)
                    if top:
                        label = f"    **Top {len(top)} recommendations:**" if len(top) > 1 else "    **Recommendation:**"
                        lines.append(label)
                        for i, p in enumerate(top, 1):
                            conf = int((p["confidence"] or 0) * 100)
                            lines.append(f"    → {i}. {p['product']} ({conf}% confidence)")
                    reason = r.get("churn_reason") or ""
                    if reason:
                        lines.append(f"    Reason: {reason}")
                reply = "\n".join(lines)
            else:
                reply = "No customers currently flagged as MEDIUM churn risk. Run analysis to refresh."
            actions = [{"type": "go_to_batch", "label": "Run batch analysis"}]
        except Exception as e:
            reply = f"Couldn't load medium risk data: {e}"

    elif intent == "low_risk_list":
        try:
            import re as _re
            recs = db.get_latest_recommendations(tenant_id)
            catalog = db.get_product_catalog(tenant_id)
            cust_map = {c["customer_id"]: c for c in db.get_customers(tenant_id)}
            low = [r for r in recs if (r.get("churn_risk") or "").upper() == "LOW"]
            # Parse optional count limit: "top 3", "last three", etc. — skip "top 3 products" (that's per-customer)
            _word_nums = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}
            _lm = _re.search(r'\b(top|last|first|latest)\s+(\d+|one|two|three|four|five|ten)\b(?!\s+products?)', message.lower())
            if _lm:
                _n_raw = _lm.group(2)
                _n = _word_nums.get(_n_raw, int(_n_raw) if _n_raw.isdigit() else None)
                if _n:
                    low = low[-_n:] if "last" in _lm.group(1) else low[:_n]
            if low:
                lines = [f"🟢 **LOW Churn Risk Customers ({len(low)}):**\n"]
                for r in low:
                    cust = cust_map.get(r["customer_id"], {})
                    lines.append(f"  • **{r.get('customer_name', r['customer_id'])}**")
                    top = _top_products(cust, r, catalog, limit=3)
                    if top:
                        label = f"    **Top {len(top)} recommendations:**" if len(top) > 1 else "    **Recommendation:**"
                        lines.append(label)
                        for i, p in enumerate(top, 1):
                            conf = int((p["confidence"] or 0) * 100)
                            lines.append(f"    → {i}. {p['product']} ({conf}% confidence)")
                reply = "\n".join(lines)
            else:
                reply = "No LOW risk customers found. Run analysis to refresh."
            actions = [{"type": "go_to_customers", "label": "View all customers"}]
        except Exception as e:
            reply = f"Couldn't load low risk data: {e}"

    elif intent == "top_products_by_segment":
        try:
            msg_lower = message.lower()
            recs = db.get_latest_recommendations(tenant_id)
            with_rec = [r for r in recs if r.get("recommended_product")]
            # Count frequency of each recommended product
            from collections import Counter
            counts = Counter(r["recommended_product"] for r in with_rec)
            if counts:
                lines = ["**Most frequently recommended products:**\n"]
                for product, count in counts.most_common(5):
                    customers_with = [r for r in with_rec if r.get("recommended_product") == product]
                    avg_conf = int(sum((r.get("confidence") or 0) for r in customers_with) / len(customers_with) * 100)
                    total_val = sum(int(r.get("estimated_deal_value") or 0) for r in customers_with)
                    lines.append(f"  **{product}**")
                    lines.append(f"  • Recommended to: {count} customers")
                    lines.append(f"  • Avg confidence: {avg_conf}%")
                    lines.append(f"  • Total opportunity: ${total_val:,}\n")
                reply = "\n".join(lines)
            else:
                reply = "No recommendations yet. Run batch analysis first."
            actions = [{"type": "go_to_batch", "label": "Run batch analysis"}]
        except Exception as e:
            reply = f"Couldn't load product data: {e}"

    elif intent == "churn_list":
        try:
            import re as _re
            recs = db.get_latest_recommendations(tenant_id)
            catalog = db.get_product_catalog(tenant_id)
            cust_map = {c["customer_id"]: c for c in db.get_customers(tenant_id)}
            high = [r for r in recs if (r.get("churn_risk") or "").upper() == "HIGH"]

            msg_lower = message.lower()
            n_match = _re.search(r'(?:top|best)\s+(\d+)', msg_lower)
            top_n = int(n_match.group(1)) if n_match else None
            
            # Sort by deal value so "Top N" makes sense (highest impact first)
            high.sort(key=lambda x: x.get("estimated_deal_value") or 0, reverse=True)
            if top_n:
                high = high[:top_n]

            # Detect compound action thresholds from the message
            email_threshold = None
            meet_threshold = None
            m = _re.search(r'confidence\s+(?:score[s]?\s+)?(?:above|over|greater than|>)\s*(\d+)\s*%', msg_lower)
            if m:
                email_threshold = int(m.group(1))
            m2 = _re.search(r'(?:upsell\s+value|deal\s+value|value)\s+(?:above|over|greater than|>)\s*\$?([\d,]+)', msg_lower)
            if m2:
                meet_threshold = int(m2.group(1).replace(",", ""))

            def _rec_top3(r):
                cust = cust_map.get(r["customer_id"], {})
                return _top_products(cust, r, catalog, limit=3)

            if high:
                label = f"🔴 **HIGH Churn Risk Customers ({len(high)}{' shown' if top_n else ''}):**\n"
                lines = [label]
                for r in high:
                    reason = r.get('churn_reason') or 'Unknown reason'
                    lines.append(f"  • **{r.get('customer_name', r['customer_id'])}**")
                    top = _rec_top3(r)
                    if top:
                        label = f"    - **Top {len(top)} products:**" if len(top) > 1 else "    - **Recommended product:**"
                        lines.append(label)
                        for i, p in enumerate(top, 1):
                            conf = int((p["confidence"] or 0) * 100)
                            lines.append(f"    → {i}. {p['product']} ({conf}% confidence)")
                    elif r.get("retention_action"):
                        lines.append(f"    - **Retention Action:** {r['retention_action']}")
                    lines.append(f"    - **Reasoning:** {reason}")

                # Append compound-action summary if thresholds were requested
                if email_threshold is not None:
                    eligible_email = [
                        r for r in high
                        if (r.get("confidence") or 0) * 100 >= email_threshold
                    ]
                    lines.append("")
                    if eligible_email:
                        lines.append(f"📧 **Email eligible (confidence ≥ {email_threshold}%):** {len(eligible_email)} customer(s)")
                        for r in eligible_email:
                            conf = int((r.get("confidence") or 0) * 100)
                            lines.append(f"  • **{r.get('customer_name', r['customer_id'])}** — {conf}% confidence")
                    else:
                        lines.append(f"📧 **Email eligible (confidence ≥ {email_threshold}%):** None of the high-risk customers meet this threshold currently.")

                if meet_threshold is not None:
                    eligible_meet = [
                        r for r in high
                        if (r.get("estimated_deal_value") or 0) >= meet_threshold
                    ]
                    lines.append("")
                    if eligible_meet:
                        lines.append(f"📅 **Meeting eligible (upsell value ≥ ${meet_threshold:,}):** {len(eligible_meet)} customer(s)")
                        for r in eligible_meet:
                            deal = int(r.get("estimated_deal_value") or 0)
                            lines.append(f"  • **{r.get('customer_name', r['customer_id'])}** — ${deal:,} estimated value")
                    else:
                        lines.append(f"📅 **Meeting eligible (upsell value ≥ ${meet_threshold:,}):** No high-risk customers exceed this threshold.")

                reply = "\n".join(lines)
                actions = []
            else:
                reply = "No customers are currently flagged as HIGH churn risk. Run analysis to update the data."
                actions = [{"type": "go_to_batch", "label": "Run batch analysis"}]
        except Exception as e:
            reply = f"Couldn't load churn data: {e}"

    elif intent == "compound_churn_action":
        try:
            import re as _re
            recs = db.get_latest_recommendations(tenant_id)
            catalog = db.get_product_catalog(tenant_id)
            cust_map = {c["customer_id"]: c for c in db.get_customers(tenant_id)}
            high = [r for r in recs if (r.get("churn_risk") or "").upper() == "HIGH"]

            def _parse_threshold(subject_pattern, text):
                """Returns (op, value) where op is '>=' or '<', or (None, None).
                Handles both directions — "above/over/greater than/>=/>" and
                "below/under/less than/lesser than/lower than/<=/<" — since a
                plain substring match on ">" alone silently dropped every
                "less than $X" filter before this fix."""
                m = _re.search(
                    rf'{subject_pattern}\s*(?:above|over|greater than|higher than|>=|>)\s*\$?([\d,]+)\s*%?',
                    text, _re.I)
                if m:
                    return ">=", float(m.group(1).replace(",", ""))
                m = _re.search(
                    rf'{subject_pattern}\s*(?:below|under|less than|lesser than|lower than|<=|<)\s*\$?([\d,]+)\s*%?',
                    text, _re.I)
                if m:
                    return "<", float(m.group(1).replace(",", ""))
                return None, None

            conf_op, conf_threshold = _parse_threshold(r'confidence\s+(?:score[s]?\s+)?', message)
            deal_op, deal_threshold = _parse_threshold(
                r'(?:upsell\s+value|deal\s+value|estimated\s+(?:upsell\s+)?value|value|revenue)', message)

            msg_lower = message.lower()
            wants_email = any(k in msg_lower for k in ["email", "send email", "mail the", "mail them"])
            wants_meeting = any(k in msg_lower for k in ["schedule", "meeting", "book a call", "book a meeting", "calendar", "google meet"])

            def _matches_conf(r):
                if conf_threshold is None:
                    return True
                c = (r.get("confidence") or 0) * 100
                return c >= conf_threshold if conf_op == ">=" else c < conf_threshold

            def _matches_deal(r):
                if deal_threshold is None:
                    return True
                v = r.get("estimated_deal_value") or 0
                return v >= deal_threshold if deal_op == ">=" else v < deal_threshold

            # Two thresholds only mean two INDEPENDENT action-eligibility bars
            # when the query actually names two different actions (email +
            # meeting) — that's when "confidence -> email, deal value ->
            # meeting" makes sense as a union with per-action tags. Without
            # that action language, "confidence above X and value below Y" is
            # a plain filter on ONE list — both conditions must hold on the
            # same customer, i.e. a straight AND/intersection.
            two_independent_actions = wants_email and wants_meeting and conf_threshold is not None and deal_threshold is not None

            def _qualifies_email(r):
                return conf_threshold is None or _matches_conf(r)

            def _qualifies_meeting(r):
                return deal_threshold is None or _matches_deal(r)

            if two_independent_actions:
                # Genuinely two different actions with their own bars — show
                # the union, tag each customer with whichever action(s) they
                # clear, rather than an intersection (which silently produces
                # zero results the moment the two criteria don't overlap) or
                # two duplicate lists.
                display = [r for r in high if _qualifies_email(r) or _qualifies_meeting(r)]
            else:
                # Plain filter (no action, or only one action, or both
                # thresholds describing the same list) — every stated
                # condition must hold on the same customer.
                display = [r for r in high if _matches_conf(r) and _matches_deal(r)]
            display.sort(key=lambda x: x.get("estimated_deal_value") or 0, reverse=True)

            def _op_word(op):
                return "≥" if op == ">=" else "<"

            filter_desc = []
            if conf_threshold is not None:
                suffix = " for email" if two_independent_actions else ""
                filter_desc.append(f"confidence {_op_word(conf_op)} {int(conf_threshold)}%{suffix}")
            if deal_threshold is not None:
                suffix = " for meetings" if two_independent_actions else ""
                filter_desc.append(f"value {_op_word(deal_op)} ${deal_threshold:,.0f}{suffix}")
            header_suffix = f" ({'; '.join(filter_desc)})" if filter_desc else ""

            if display:
                lines = [f"🔴 **HIGH Churn Risk Customers{header_suffix} — {len(display)} found:**", ""]
                bulk_actions = []
                for r in display:
                    cust = cust_map.get(r["customer_id"], {})
                    deal = int(r.get("estimated_deal_value") or 0)
                    conf = int((r.get("confidence") or 0) * 100)
                    name = r.get("customer_name", r["customer_id"])
                    entry = [f"• **{name}** — {conf}% confidence | ${deal:,} estimated value"]
                    top = _top_products(cust, r, catalog, limit=3)
                    for i, p in enumerate(top, 1):
                        c = int((p["confidence"] or 0) * 100)
                        entry.append(f"  → {i}. {p['product']} ({c}% confidence)")

                    tags = []
                    if wants_email and _qualifies_email(r):
                        tags.append(f"✅ email eligible" + (f" (≥{conf_threshold}%)" if conf_threshold is not None else ""))
                        bulk_actions.append({"type": "send_email", "label": f"Email {name}", "customer_id": r["customer_id"]})
                    if wants_meeting and _qualifies_meeting(r):
                        tags.append(f"✅ meeting eligible" + (f" (≥${deal_threshold:,})" if deal_threshold is not None else ""))
                        bulk_actions.append({"type": "schedule_meeting", "label": f"Schedule with {name}", "customer_id": r["customer_id"]})
                    if tags:
                        entry.append(f"  • {' | '.join(tags)}")
                    lines.append("\n".join(entry))
                    lines.append("")

                note_parts = []
                if wants_email:
                    note_parts.append("send the emails")
                if wants_meeting:
                    note_parts.append("schedule the meetings")
                if note_parts:
                    lines.append(f"Click below to {' or '.join(note_parts)} for the eligible customers.")
                reply = "\n".join(lines).rstrip()
                actions = bulk_actions[:6] if bulk_actions else []
            else:
                reason = f" matching {', '.join(filter_desc)}" if filter_desc else ""
                reply = f"No HIGH churn risk customers{reason}. Try loosening the threshold, or run batch analysis to refresh the data."
                actions = [{"type": "go_to_batch", "label": "Run batch analysis"}]
        except Exception as e:
            reply = f"Couldn't process compound churn action: {e}"

    elif intent == "custom_rec_and_regenerate":
        try:
            import re as _re
            from app.pipeline import generate_recommendations
            from collections import Counter

            # Extract product name from query
            catalog = db.get_product_catalog(tenant_id)
            customers = db.get_customers(tenant_id)

            # Try to match product name from catalog against the message
            msg_lower = message.lower()
            matched_product = None
            for p in catalog:
                name = p.get("product_name", "")
                if name.lower() in msg_lower:
                    matched_product = name
                    break

            # Find eligible customers (those who don't have this product already)
            if matched_product:
                eligible = [
                    c for c in customers
                    if matched_product.lower() not in (c.get("plan_tier") or "").lower()
                    and matched_product.lower() not in (c.get("current_product") or "").lower()
                ]
                eligible_count = len(eligible)
            else:
                eligible = customers
                eligible_count = len(customers)

            # Run batch regeneration
            result = generate_recommendations(tenant_id=tenant_id, force_include=False)
            summary_text, analytics_data = _analytics_summary(tenant_id)

            if matched_product:
                reply = (
                    f"**Custom Recommendation: {matched_product}**\n\n"
                    f"Found **{eligible_count}** eligible customers (not yet on {matched_product}).\n\n"
                    f"Batch analysis has been regenerated for all **{len(result)}** customers.\n\n"
                    + summary_text
                )
            else:
                reply = (
                    f"I couldn't match a specific product from your catalog in that query.\n"
                    f"Available products: {', '.join(p.get('product_name','') for p in catalog[:5])}...\n\n"
                    f"I still ran the full batch analysis:\n\n" + summary_text
                )

            recs = db.get_latest_recommendations(tenant_id)
            with_rec = [r for r in recs if r.get("recommended_product")]
            counts = Counter(r["recommended_product"] for r in with_rec)
            if counts:
                lines = ["\n**Recommended products (with confidence):**"]
                for product, count in counts.most_common():
                    same = [r for r in with_rec if r.get("recommended_product") == product]
                    avg_conf = int(sum((r.get("confidence") or 0) for r in same) / len(same) * 100)
                    total_val = sum(int(r.get("estimated_deal_value") or 0) for r in same)
                    lines.append(f"  • **{product}** — {avg_conf}% avg confidence · {count} customers · ${total_val:,} opportunity")
                reply += "\n" + "\n".join(lines)
            actions = [{"type": "go_to_customers", "label": "View all customers"}]
        except Exception as e:
            reply = f"Couldn't process custom recommendation: {e}"

    elif intent == "batch_run":
        try:
            from app.pipeline import generate_recommendations
            from collections import Counter
            result = generate_recommendations(tenant_id=tenant_id, force_include=False)
            reply, analytics_data = _analytics_summary(tenant_id)
            reply = f"**Batch Analysis Complete!**\n\nI analyzed **{len(result)}** customers. Here are the results:\n\n" + reply

            recs = db.get_latest_recommendations(tenant_id)
            with_rec = [r for r in recs if r.get("recommended_product")]
            counts = Counter(r["recommended_product"] for r in with_rec)
            if counts:
                lines = ["\n**Recommended products (with confidence):**"]
                for product, count in counts.most_common():
                    same = [r for r in with_rec if r.get("recommended_product") == product]
                    avg_conf = int(sum((r.get("confidence") or 0) for r in same) / len(same) * 100)
                    total_val = sum(int(r.get("estimated_deal_value") or 0) for r in same)
                    lines.append(f"  • **{product}** — {avg_conf}% avg confidence · {count} customers · ${total_val:,} opportunity")
                reply += "\n" + "\n".join(lines)
            actions = [{"type": "go_to_customers", "label": "View all customers"}]
        except Exception as e:
            reply = f"Sorry, the batch evaluation failed: {e}"
            actions = []
    elif intent == "catalog_query":
        catalog = db.get_product_catalog(tenant_id)
        if catalog:
            lines = ["Here are the products currently available in your Upsell Catalog:\n"]
            for p in catalog:
                try:
                    price_val = p.get("price") or p.get("price_per_seat") or p.get("seat_price_usd") or p.get("unit_price") or 0
                    price = float(price_val)
                    price_str = f"${price:,.2f}" if price % 1 != 0 else f"${int(price):,}"
                except (ValueError, TypeError):
                    price_str = "$0"
                lines.append(f"- **{p.get('product_name')}** ({price_str})")
            reply = "\n".join(lines)
        else:
            reply = "You don't have any products in your catalog yet."
        actions = []

    elif intent == "feature_weights":
        try:
            w = db.get_feature_weights(tenant_id)
            if w:
                reply = "Current feature weights:\n" + "\n".join(f"- {k}: {v}x" for k, v in w.items()) + "\n\nAdjust these in Settings."
            else:
                reply = "No custom feature weights set. All features weighted equally. Configure in Settings."
        except Exception:
            reply = "Configure feature weights in the Settings page."
        actions = [{"type": "go_to_settings", "label": "Configure weights"}]

    else:
        reply = (
            "I'm designed to help with **customer analytics, upsell recommendations, churn risk, and sales actions** only.\n\n"
            "Here are some things you can ask me:\n"
            "- **Show me [customer name]** — view a customer profile\n"
            "- **High churn risk customers** — list at-risk accounts\n"
            "- **Analytics overview** — see a summary dashboard\n"
            "- **Run recommendations for all customers** — batch analysis\n"
            "- **What products are in the catalog?** — browse products"
        )

    _add_to_history(session, "user", message)
    _add_to_history(session, "assistant", reply)
    return {"conversation_id": cid, "reply": reply, "intent": intent,
            "customer_data": customer_data, "analytics_data": analytics_data, "actions": actions}


def list_sessions(tenant_id: str) -> list:
    try:
        return db.list_chat_sessions_db(tenant_id)
    except Exception:
        # Fallback to in-memory if DB not ready yet
        return [
            {"conversation_id": sid, "created_at": s.get("created_at"),
             "last_customer": s.get("last_customer_name"),
             "first_message": s.get("first_message"),
             "turns": len(s.get("history", [])) // 2}
            for sid, s in _sessions.items() if s.get("tenant_id") == tenant_id
        ]


def clear_session(conversation_id: str, tenant_id: str) -> bool:
    _sessions.pop(conversation_id, None)
    try:
        return db.delete_chat_session_db(conversation_id, tenant_id)
    except Exception:
        return False

def get_session_history(conversation_id: str, tenant_id: str) -> list:
    s = _sessions.get(conversation_id)
    if s and s.get("tenant_id") == tenant_id:
        return s.get("history", [])
    try:
        persisted = db.load_chat_session(conversation_id, tenant_id)
        if persisted:
            return persisted.get("history", [])
    except Exception:
        pass
    return []