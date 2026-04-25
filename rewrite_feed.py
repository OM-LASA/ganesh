"""
scripts/rewrite_feed.py
=======================
Content intelligence layer — The Streamic.

Changes from v1:
  • Short, factual scaffold bodies (150–220 words) — no filler, no padding
  • Classification fields added: topic_type, priority_for_insights,
    technical_keywords, needs_gemini
  • topic_type detected from title + teaser keywords
  • priority_for_insights = True for high-signal technical items from trusted sources
  • needs_gemini = True for high-priority, non-editorial items (picked up by
    generate_summaries.py for full article generation, capped at 3–5/run)
  • All other behaviour, output keys, and JSON structure unchanged
"""

import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NEWS_F   = os.path.join(ROOT, "data", "news.json")
POOLS_F  = os.path.join(ROOT, "data", "image_pools.json")
OUTPUT_F = os.path.join(ROOT, "data", "generated_articles.json")

MAX_STORIES_PER_RUN = 20
MAX_TOTAL_KEPT      = 400
CARD_WORD_TARGET    = 170
# ↓ scaffold target: 150–220 words only
SCAFFOLD_WORD_TARGET = 190
MIN_PER_CATEGORY    = 1
MAX_PER_CATEGORY    = 5

CAT_META = {
    "featured":           {"label":"Featured",            "icon":"⭐","color":"#1d1d1f","page":"featured.html",              "weight": 1.15},
    "streaming":          {"label":"Streaming",           "icon":"📡","color":"#0071e3","page":"streaming.html",             "weight": 1.10},
    "cloud":              {"label":"Cloud Production",    "icon":"☁️","color":"#5856d6","page":"cloud.html",                 "weight": 1.08},
    "graphics":           {"label":"Graphics",            "icon":"🎨","color":"#FF9500","page":"graphics.html",              "weight": 0.92},
    "playout":            {"label":"Playout",             "icon":"▶️","color":"#34C759","page":"playout.html",               "weight": 1.02},
    "infrastructure":     {"label":"Infrastructure",      "icon":"🏗️","color":"#8E8E93","page":"infrastructure.html",        "weight": 1.10},
    "ai-post-production": {"label":"AI & Post-Production","icon":"🎬","color":"#FF2D55","page":"ai-post-production.html",   "weight": 1.05},
    "newsroom":           {"label":"Newsroom",            "icon":"📰","color":"#D4AF37","page":"newsroom.html",              "weight": 1.12},
}

TRUSTED_SOURCE_BONUS = {
    "AWS": 8, "TV Technology": 8, "BroadcastBeat": 7, "Haivision": 6,
    "Telestream": 6, "Vizrt": 6, "Harmonic": 6, "Frame.io": 5,
    "Avid Press Room": 5, "Streaming Media Blog": 6, "Microsoft Security": 7,
}

KEYWORD_BONUS = {
    "nab": 10, "ibc": 8, "cloud": 7, "ai": 7, "automation": 6,
    "streaming": 7, "ott": 7, "cdn": 7, "latency": 6, "sports": 5,
    "newsroom": 7, "st 2110": 9, "smpte": 8, "jpeg xs": 8, "drm": 6,
    "ad insertion": 7, "ssai": 7, "media asset": 6, "metadata": 6,
}

BOILERPLATE = re.compile(
    r"\b(today announced|is pleased to announce|proud to introduce|we are excited|leading provider of|industry-leading|state-of-the-art|cutting-edge|revolutionary|game-changing|best-in-class|world-class)\b",
    re.IGNORECASE,
)

# ── Topic Classification ──────────────────────────────────────────────────────

TOPIC_TYPE_RULES = [
    ("ai_metadata",             ["ai ", "machine learning", "artificial intelligence", "metadata", "ml model", "computer vision", "auto-tag", "speech-to-text", "stt", "transcription", "facial recognition"]),
    ("newsroom_workflow",       ["newsroom", "nrcs", "inews", "mediacentral", "dalet", "rundown", "wire service", "editorial", "journalist"]),
    ("broadcast_infrastructure",["st 2110", "smpte", "sdi", "hd-sdi", "ip core", "ndi", "dante", "aes67", "ip routing", "signal path", "multiviewer", "router"]),
    ("streaming_delivery",      ["hls", "dash", "cdn", "ott", "streaming", "latency", "abr", "bitrate", "origin", "edge", "manifest", "drm", "widevine", "playready"]),
    ("cloud_production",        ["aws", "azure", "gcp", "cloud", "serverless", "saas", "media services", "elemental", "mediaconnect", "kubernetes", "orchestration"]),
    ("postproduction",          ["avid", "adobe premiere", "davinci resolve", "blackmagic", "post-production", "finishing", "color grade", "vfx", "render"]),
    ("playout_automation",      ["playout", "pebble", "harmonic", "mediagenix", "playlist", "channel-in-a-box", "mcr", "automation", "traffic", "schedule"]),
    ("storage_management",      ["storage", "san", "nexis", "nearline", "archive", "lto", "mam", "pam", "asset management", "interplay", "ingest"]),
]

TECHNICAL_KEYWORD_LIST = [
    "st 2110", "sdi", "ndi", "aes67", "hls", "dash", "cdn", "ott", "abr",
    "latency", "drm", "ssai", "mam", "pam", "nrcs", "inews", "avid",
    "ai", "metadata", "cloud", "kubernetes", "playout", "ingest", "archive",
    "lto", "san", "multiviewer", "smpte", "jpeg xs", "hevc", "av1", "nab", "ibc",
]


def _classify_topic(title: str, teaser: str) -> str:
    text = f"{title} {teaser}".lower()
    for topic_type, keywords in TOPIC_TYPE_RULES:
        if any(kw in text for kw in keywords):
            return topic_type
    return "broadcast_infrastructure"  # safe default


def _extract_technical_keywords(title: str, teaser: str) -> list:
    text = f"{title} {teaser}".lower()
    return [kw for kw in TECHNICAL_KEYWORD_LIST if kw in text]


def _set_priority(item: dict, topic_type: str) -> bool:
    """Looser, production-grade priority logic for homepage-quality filtering."""
    src   = item.get("source") or item.get("source_domain") or ""
    score = item.get("score", 0)
    cat   = item.get("category", "")

    title  = (item.get("title") or "").lower()
    teaser = (item.get("teaser") or item.get("description") or "").lower()
    text   = f"{title} {teaser}"

    trusted     = src in TRUSTED_SOURCE_BONUS
    high_score  = score >= 55
    strong_cat  = cat in {"featured", "newsroom", "infrastructure", "cloud", "streaming"}

    strong_keywords = any(k in text for k in [
        "st 2110", "cdn", "ai", "metadata", "playout", "nexis",
        "mediacentral", "vizrt", "harmonic", "pebble", "aws",
        "latency", "drm", "ssai", "nmos",
    ])

    return trusted or high_score or strong_cat or strong_keywords


# ── Core helpers (unchanged) ──────────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r"\s{2,}", " ", BOILERPLATE.sub("", text or "")).strip()


def _split_sents(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", _clean(text)) if s.strip()]


def _hash_int(*parts: str) -> int:
    return int(hashlib.md5("::".join(parts).encode()).hexdigest(), 16)


def make_slug(title, pub_date, cat=""):
    date_part  = (pub_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    cat_part   = re.sub(r"[^\w]", "-", (cat or "").lower()).strip("-")[:12]
    title_part = re.sub(r"[^\w\s-]", "", title.lower())
    title_part = re.sub(r"[\s_]+", "-", title_part).strip("-")
    prefix     = f"{date_part}-{cat_part}-" if cat_part else f"{date_part}-"
    return f"{prefix}{title_part[:65 - len(prefix)]}"


def pick_image(cat, slug, pools):
    cat_pool = pools.get("cat_pools", {}).get(cat, [])
    if not cat_pool:
        cat_pool = [p for lst in pools.get("cat_pools", {}).values() for p in lst] or ["photo-1598488035139-bdbb2231ce04"]
    idx = _hash_int(cat, slug) % len(cat_pool)
    return {
        "image_url":         f"https://images.unsplash.com/{cat_pool[idx]}?w=1200&auto=format&fit=crop&q=80",
        "image_credit":      "Photo: Unsplash — free to use under the Unsplash License",
        "image_license":     "Unsplash License",
        "image_license_url": "https://unsplash.com/license",
    }


def score_item(item):
    title  = (item.get("title") or "").lower()
    teaser = (item.get("teaser") or item.get("description") or "").lower()
    text = f"{title} {teaser}"
    cat = item.get("category") or "featured"
    src = item.get("source") or item.get("source_domain") or ""
    score = 40.0 * CAT_META.get(cat, {"weight": 1.0})["weight"]
    score += TRUSTED_SOURCE_BONUS.get(src, 0)
    for kw, bonus in KEYWORD_BONUS.items():
        if kw in text:
            score += bonus
    if item.get("image"):
        score += 3
    if len(teaser.split()) >= 12:
        score += 6
    pub = (item.get("published") or item.get("pubDate") or "")[:10]
    if pub:
        try:
            days = (datetime.now(timezone.utc).date() - datetime.fromisoformat(pub).date()).days
            score += max(0, 10 - days)
        except Exception:
            pass
    score += (_hash_int(title, src) % 100) / 1000.0
    return score


def flatten_news(news_raw):
    if isinstance(news_raw, list):
        items = news_raw
    else:
        items = []
        for cat, rows in (news_raw or {}).items():
            for row in (rows or []):
                row = dict(row)
                row.setdefault("category", cat)
                items.append(row)
    return items


def select_best_items(news_items):
    scored = []
    for row in news_items:
        if not row.get("title"):
            continue
        row = dict(row)
        row["category"] = row.get("category") or "featured"
        row["score"] = score_item(row)
        scored.append(row)
    scored.sort(key=lambda x: (x["score"], x.get("published") or x.get("pubDate") or ""), reverse=True)

    selected = []
    per_cat = defaultdict(int)
    used_titles = set()

    for row in scored:
        cat = row["category"]
        title_key = row["title"].strip().lower()
        if per_cat[cat] >= MIN_PER_CATEGORY or title_key in used_titles:
            continue
        selected.append(row)
        per_cat[cat] += 1
        used_titles.add(title_key)
        if len(selected) >= min(MAX_STORIES_PER_RUN, len(CAT_META)):
            break

    for row in scored:
        if len(selected) >= MAX_STORIES_PER_RUN:
            break
        cat = row["category"]
        title_key = row["title"].strip().lower()
        if title_key in used_titles or per_cat[cat] >= MAX_PER_CATEGORY:
            continue
        selected.append(row)
        per_cat[cat] += 1
        used_titles.add(title_key)

    selected.sort(key=lambda x: (x.get("published") or x.get("pubDate") or "", x["score"]), reverse=True)
    return selected


# ── Scaffold body builder ─────────────────────────────────────────────────────
# Replaces build_article_body. Produces 150–220 words of clean, factual scaffold.
# No filler phrases. generate_summaries.py will replace this for needs_gemini items.

def build_scaffold_body(title: str, teaser: str, cat: str, source: str, topic_type: str) -> tuple:
    """
    Build a short, factual scaffold body (150–220 words).
    Explicit 3-part structure: what happened / where it applies / why it matters.
    generate_gemini.py replaces this for needs_gemini=True items.
    """
    teaser    = _clean(teaser)
    sents     = _split_sents(f"{title}. {teaser}")
    lead      = sents[0] if sents else title
    detail    = sents[1] if len(sents) > 1 else teaser
    cat_label = CAT_META.get(cat, CAT_META["featured"])["label"]

    # PART 2 — where it applies: topic-specific, concrete, no filler
    where_it_applies = {
        "ai_metadata": (
            f"This applies across {cat_label.lower()} pipelines where AI-assisted metadata, "
            f"auto-tagging, and speech-to-text reduce manual logging time and improve archive "
            f"searchability inside MAM systems such as Avid MediaCentral or Dalet."
        ),
        "newsroom_workflow": (
            f"The impact is felt directly in NRCS-driven workflows — how rundowns, wire feeds, "
            f"and editorial assignments move between iNews or MediaCentral and the production "
            f"chain. Friction in that handoff costs time on air."
        ),
        "broadcast_infrastructure": (
            f"At infrastructure level, this touches signal routing and transport — the ST 2110 "
            f"or SDI fabric connecting cameras, production switchers, graphics engines, and "
            f"distribution paths, where timing, redundancy, and IP routing behaviour all matter."
        ),
        "streaming_delivery": (
            f"For streaming teams, the relevant chain runs from origin through CDN edge to "
            f"player: ABR ladder design, CMAF chunked delivery, LL-HLS latency, DRM packaging, "
            f"and SSAI insertion points are all potentially in scope."
        ),
        "cloud_production": (
            f"Cloud production workflows built on AWS MediaConnect, MediaLive, or equivalent "
            f"Azure/GCP services are the primary target here — with egress cost, failover "
            f"design, and hybrid on-prem integration as the practical pressure points."
        ),
        "postproduction": (
            f"Post pipelines running Avid Media Composer with Nexis shared storage, or Resolve "
            f"with SAN-attached media, are affected through ingest throughput, proxy workflow "
            f"design, audio conformance (AES67/loudness), and export-to-delivery speed."
        ),
        "playout_automation": (
            f"Playout systems — Pebble Control, Harmonic Spectrum, or Mediagenix WHATS'On — "
            f"are the operational target. Playlist scheduling, SCTE-35 ad triggering, MCR "
            f"redundancy, and channel-in-a-box architecture are the key decision points."
        ),
        "storage_management": (
            f"Storage architecture spans nearline NVMe or SAN, LTO cold archive, and cloud "
            f"object tiers. The MAM integration layer — Avid Interplay, Dalet, or equivalent — "
            f"determines how quickly assets move between tiers under deadline pressure."
        ),
    }.get(topic_type, (
        f"This is relevant to {cat_label.lower()} teams evaluating tooling or workflow changes. "
        f"The integration points to watch are ingest, MAM, playout, and distribution — where "
        f"a change in one layer creates knock-on effects across the others."
    ))

    # PART 3 — why it matters: cost / speed / reliability framing
    why_it_matters = (
        f"The practical question for engineering leads: does this change cost, throughput, "
        f"reliability, or editorial speed in a measurable way? Map it against real workflows "
        f"before treating any vendor claim as production-ready."
    )

    paras = [
        f"<p><strong>{lead}</strong> {detail}</p>",
        f"<p>{where_it_applies}</p>",
        f"<p>{why_it_matters}</p>",
    ]

    body = "\n".join(paras)
    wc   = len(re.sub(r"<[^>]+>", " ", body).split())
    return body, wc


def build_card_summary(title: str, teaser: str, cat: str, source: str) -> str:
    teaser = _clean(teaser)
    sents  = _split_sents(f"{title}. {teaser}")
    lead   = sents[1] if len(sents) > 1 else teaser or title
    words  = lead.split()
    return " ".join(words[:CARD_WORD_TARGET])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== rewrite_feed.py ===")
    with open(NEWS_F, "r", encoding="utf-8") as f:
        news_raw = json.load(f)
    with open(POOLS_F, "r", encoding="utf-8") as f:
        pools = json.load(f)

    existing = []
    if os.path.exists(OUTPUT_F):
        with open(OUTPUT_F, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except Exception:
                existing = []

    existing_by_slug = {a.get("slug"): a for a in existing if a.get("slug")}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    selected = select_best_items(flatten_news(news_raw))
    print(f"Selected best RSS items this run: {len(selected)}")

    fresh_articles = []
    touched_slugs  = set()

    for item in selected:
        cat     = item.get("category", "featured")
        meta    = CAT_META.get(cat, CAT_META["featured"])
        title   = (item.get("title") or "").strip()
        teaser  = (item.get("teaser") or item.get("description") or "").strip()
        pub     = (item.get("published") or item.get("pubDate") or today)[:10]
        src_url = item.get("url") or item.get("link") or ""
        src_dom = item.get("source") or item.get("source_domain") or ""
        slug    = make_slug(title, pub, cat)
        touched_slugs.add(slug)
        score   = item.get("score", 0)

        # ── Classification ────────────────────────────────────────────────────
        topic_type         = _classify_topic(title, teaser)
        technical_keywords = _extract_technical_keywords(title, teaser)
        priority_for_insights = _set_priority(item, topic_type)
        # needs_gemini: high-priority AND not already editorial
        old = existing_by_slug.get(slug, {})
        already_editorial = bool(old.get("is_editorial") or old.get("editorial"))
        needs_gemini = (
            priority_for_insights
            and not already_editorial
            and len(teaser.split()) > 8
        )

        image_meta = pick_image(cat, slug, pools)
        body_html, word_count = build_scaffold_body(title, teaser, cat, src_dom, topic_type)

        article = {
            # ── Core fields (unchanged keys) ──────────────────────────────────
            "category":         cat,
            "cat_label":        meta["label"],
            "cat_icon":         meta["icon"],
            "cat_color":        meta["color"],
            "cat_page":         meta["page"],
            "title":            title,
            "slug":             slug,
            "dek":              teaser[:180] if teaser else title,
            "meta_description": teaser[:220] if teaser else title,
            "card_summary":     build_card_summary(title, teaser, cat, src_dom),
            "body_html":        body_html,
            "word_count":       word_count,
            "source_url":       src_url,
            "source_domain":    src_dom,
            "published":        pub,
            "story_rank":       score,
            "analysis_level":   "scaffold",
            "generated_by":     "rewrite_feed_local",
            **image_meta,
            # ── New classification fields (backward-compatible additions) ─────
            "topic_type":             topic_type,
            "priority_for_insights":  priority_for_insights,
            "technical_keywords":     technical_keywords,
            "needs_gemini":           needs_gemini,
        }

        # Preserve existing higher-quality editorial overrides
        if already_editorial:
            article.update({k: old[k] for k in old.keys() if k not in {"story_rank"}})
        elif old:
            for k in ["card_summary", "body_html", "word_count", "generated_by",
                      "quality_score", "needs_gemini", "topic_type", "technical_keywords"]:
                if old.get(k) is not None:
                    article[k] = old[k]

        fresh_articles.append(article)

    untouched_existing = [a for a in existing if a.get("slug") not in touched_slugs]
    merged = fresh_articles + untouched_existing
    merged.sort(key=lambda a: (a.get("published") or "", a.get("story_rank") or 0), reverse=True)
    merged = merged[:MAX_TOTAL_KEPT]

    # Summary stats
    needs_gemini_count    = sum(1 for a in fresh_articles if a.get("needs_gemini"))
    high_priority_count   = sum(1 for a in fresh_articles if a.get("priority_for_insights"))
    topic_dist            = defaultdict(int)
    for a in fresh_articles:
        topic_dist[a.get("topic_type", "unknown")] += 1

    with open(OUTPUT_F, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"✓ generated_articles.json: {len(merged)} total ({len(fresh_articles)} refreshed from latest RSS)")
    print(f"  → High priority:  {high_priority_count}")
    print(f"  → Needs Gemini:   {needs_gemini_count} (will be picked up by generate_summaries.py)")
    print(f"  → Topic breakdown: {dict(topic_dist)}")


if __name__ == "__main__":
    main()
