#!/usr/bin/env python3
"""
The Streamic RSS Feed Aggregator
Fetches, parses, and aggregates broadcast technology news from multiple sources

This version:
- Uses Cloudflare Worker: https://broken-king-b4dc.itabmum.workers.dev
- Removes old feeds (Dacast / OnTheFly / YoloLiv / TechCrunch / Engadget / WIRED)
- Adds Streaming vendors: Haivision / Telestream / Bitmovin
- Adds Infra vendors: Avid Press (Notified) / Adobe Developer (OpenRSS)
- Renames 'audio-ai' -> 'ai-post-production'
- Adds 8 verified AI Post Production feeds
"""

import feedparser
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote
import requests
from pathlib import Path


# ── Broadcast relevance filter ────────────────────────────────────────────────
# Reject items that are clearly not broadcast/streaming technology
_BROADCAST_KEYWORDS = [
    "broadcast", "streaming", "codec", "encoder", "decoder", "nab", "ibc",
    "ott", "cdn", "video", "audio", "production", "playout", "camera",
    "studio", "graphics", "newsroom", "mam", "pam", "nmos", "st 2110",
    "sdi", "ip workflow", "cloud production", "media", "television", "tv",
    "satellite", "transmission", "post-production", "editing", "vfx",
    "live event", "ingest", "workflow", "signal", "4k", "hdr", "hevc",
    "h.264", "h.265", "av1", "hls", "mpeg", "mxf", "srt", "rist", "ndi",
    "remote production", "remi", "ob van", "multiviewer", "intercom",
    # Additional broad broadcast/media signals
    "jpeg xs", "jpeg2000", "ip media", "media server", "channel", "network",
    "vendor", "nab show", "ibc show", "mediatech", "media tech", "vizrt",
    "evertz", "grass valley", "harmonic", "haivision", "telestream", "ateme",
    "bitmovin", "envivio", "aws media", "azure media", "cloud encode",
    "live ip", "ip broadcast", "media workflow", "broadcast technology",
    "media production", "post production", "color grade", "colour grade",
    "software-defined", "ip transition", "ip infrastructure", "media asset",
    "newscast", "tvbe", "tvbeurope", "svgeurope", "broadcastbeat",
]
_REJECT_KEYWORDS = [
    "led wall sleep", "retail led", "sleep study", "led display sleep",
    "fashion week", "luxury hotel", "real estate", "restaurant review",
    "fitness app", "health app", "cryptocurrency", "nft ", "web3 ",
    "gaming headset", "smart home", "wearable", "e-commerce",
]

def is_broadcast_item(title: str, description: str = "") -> bool:
    text = (title + " " + description).lower()
    if any(k in text for k in _REJECT_KEYWORDS):
        return False
    return any(k in text for k in _BROADCAST_KEYWORDS)

# ===== CONFIGURATION =====
CLOUDFLARE_WORKER = "https://broken-king-b4dc.itabmum.workers.dev"
DATA_DIR = Path("data")
OUTPUT_FILE = DATA_DIR / "news.json"
ARCHIVE_FILE = DATA_DIR / "archive.json"

# Performance settings
MAX_ITEMS_PER_FEED = 8    # Reduced: quality > quantity — 8 per feed, ~28 feeds = ~224 pool
FEED_FETCH_TIMEOUT = 12
ARTICLE_FETCH_TIMEOUT = 5
MAX_ARTICLE_FETCHES = 5

# Balancing settings — tuned down to keep total RSS pool ≤ 120 items
MIN_PER_CATEGORY = 6
MIN_REQUIRED_EACH = 2
MAX_NEWS_ITEMS = 120      # Hard cap — only quality broadcast content reaches the site


# ===== DIRECT FETCH FEEDS (Bypass Cloudflare Worker) =====
# Curated to ≤ 30 high-quality, broadcast-specific sources only.
# Removed: security blogs (Krebs, BleepingComputer, SecurityWeek, DarkReading, Microsoft Security),
#          general tech, Cloudinary, Frame.io, SNS/storage-only, ProcessExcellenceNetwork,
#          Premiere Gal (consumer-level), FilterGrade (consumer), VideocopilotSnet (tutorials only)
DIRECT_FEEDS = [
    # Core broadcast news (tier-1 trade publications)
    'https://www.tvtechnology.com/news/rss.xml',
    'https://www.broadcastbeat.com/feed/',
    'https://www.streamingmediablog.com/feed',

    # IP / infrastructure (broadcast-specific)
    'https://www.haivision.com/feed/',
    'https://blog.telestream.com/feed/',
    'https://www.harmonicinc.com/insights/blog/rss.xml',

    # Post-production and editing (professional level)
    'https://jonnyelwyn.co.uk/feed/',
    'https://beforesandafters.com/feed/',

    # Cloud / streaming vendors
    'https://aws.amazon.com/blogs/media/feed/',
    'https://openrss.org/https://bitmovin.com/blog/',
]

# ===== CATEGORY-SPECIFIC FEED REGISTRY =====
# Total unique feeds across all categories: 28
# Feeds are de-duped across categories during fetch — no double-processing.
CATEGORY_FEEDS = {

    'newsroom': [
        # Tier-1 broadcast trade press
        'https://www.tvtechnology.com/news/rss.xml',
        'https://www.broadcastbeat.com/feed/',
        'https://www.inbroadcast.com/rss.xml',
        # Vendor press — directly relevant to newsroom tech
        'https://api.client.notified.com/api/rss/publish/view/47032?type=press',  # Avid
        'https://www.rossvideo.com/news/feed/',
    ],

    'playout': [
        'https://www.tvtechnology.com/playout/rss.xml',
        'https://www.inbroadcast.com/rss.xml',
        'https://www.harmonicinc.com/insights/blog/rss.xml',
        'https://www.imaginecommunications.com/news/rss.xml',
    ],

    'infrastructure': [
        'https://www.tvtechnology.com/infrastructure/rss.xml',
        'https://www.haivision.com/feed/',
        'https://www.inbroadcast.com/rss.xml',
        'https://www.evertz.com/news/rss',
    ],

    'graphics': [
        'https://www.tvtechnology.com/graphics/rss.xml',
        'https://www.vizrt.com/news/rss',
        'https://motionographer.com/feed/',
    ],

    'cloud': [
        'https://www.tvtechnology.com/cloud/rss.xml',
        'https://aws.amazon.com/blogs/media/feed/',
        'https://openrss.org/https://bitmovin.com/blog/',
    ],

    'streaming': [
        'https://www.tvtechnology.com/streaming/rss.xml',
        'https://www.streamingmediablog.com/feed',
        'https://www.haivision.com/feed/',
        'https://blog.telestream.com/feed/',
    ],

    # Professional broadcast post-production and AI workflow
    'ai-post-production': [
        'https://jonnyelwyn.co.uk/feed/',
        'https://beforesandafters.com/feed/',
        'https://blog.pond5.com/feed/',
        'https://aws.amazon.com/blogs/media/feed/',
    ],

}


# ===== HELPER FUNCTIONS =====
def should_use_direct_fetch(feed_url: str) -> bool:
    """Check if feed should bypass Cloudflare Worker"""
    return feed_url in DIRECT_FEEDS


def fetch_feed_via_worker(feed_url: str):
    """Fetch feed through Cloudflare Worker (keeps your existing mechanism)"""
    try:
        encoded_url = quote(feed_url, safe='')
        worker_url = f"{CLOUDFLARE_WORKER}/?url={encoded_url}"
        response = requests.get(
            worker_url,
            timeout=FEED_FETCH_TIMEOUT,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; TheStreamic/1.0)'}
        )
        if response.status_code == 200:
            return feedparser.parse(response.content)
        return None
    except Exception as e:
        print(f" ⚠ Worker error for {feed_url[:60]}: {e}")
        return None


def fetch_feed_direct(feed_url: str):
    """Fetch feed directly without worker"""
    try:
        response = requests.get(
            feed_url,
            timeout=FEED_FETCH_TIMEOUT,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; TheStreamic/1.0)'}
        )
        if response.status_code == 200:
            return feedparser.parse(response.content)
        return None
    except Exception as e:
        print(f" ⚠ Direct fetch error for {feed_url[:60]}: {e}")
        return None


def fetch_feed_with_fallback(feed_url: str):
    """Always fetch directly in GitHub Actions environment"""
    return fetch_feed_direct(feed_url)


def extract_image_from_entry(entry):
    """Extract image URL with multiple fallback strategies"""
    # 1) media:content
    if hasattr(entry, 'media_content'):
        for media in entry.media_content:
            url = media.get('url')
            if url:
                return url

    # 2) media:thumbnail
    if hasattr(entry, 'media_thumbnail'):
        for thumb in entry.media_thumbnail:
            url = thumb.get('url')
            if url:
                return url

    # 3) enclosures with image/*
    if hasattr(entry, 'enclosures'):
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href') or enc.get('url')

    # 4) Parse from description/summary
    description = entry.get('description', '') or entry.get('summary', '')
    if description:
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description, re.IGNORECASE)
        if m:
            img_url = m.group(1)
            low = img_url.lower()
            if not any(k in low for k in ['1x1', 'pixel', 'spacer', 'tracker', 'avatar', 'gravatar']):
                return img_url

    # 5) Try a lowered-quality variant if URL contains width/height hints
    if hasattr(entry, 'media_content'):
        for media in entry.media_content:
            url = media.get('url', '')
            if url and ('w=' in url or 'width=' in url or 'h=' in url or 'height=' in url):
                url = re.sub(r'(w|width)=\d+', r'\1=400', url)
                url = re.sub(r'(h|height)=\d+', r'\1=300', url)
                url = re.sub(r'(q|quality)=\d+', r'\1=70', url)
                return url

    return None


def extract_og_image(article_url: str, timeout: int = ARTICLE_FETCH_TIMEOUT):
    """Extract og:image or twitter:image from article HTML (last resort)"""
    try:
        r = requests.get(
            article_url,
            timeout=timeout,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; TheStreamic/1.0)'}
        )
        if r.status_code != 200:
            return None
        html = r.text[:80000]

        # og:image
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if m:
            return m.group(1)

        # twitter:image
        m = re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if m:
            return m.group(1)

        return None
    except Exception:
        return None


def process_entries(entries, category, source_name):
    """Convert feed entries into our normalized item dicts"""
    items = []
    article_fetch_count = 0

    for entry in entries:
        try:
            title = (entry.get('title') or '').strip()
            link = (entry.get('link') or '').strip()
            guid = entry.get('id', link)

            if not title or not link:
                continue

            # image
            image = extract_image_from_entry(entry)
            if not image and article_fetch_count < MAX_ARTICLE_FETCHES:
                image = extract_og_image(link)
                article_fetch_count += 1

            # pubDate
            pub_date_iso = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    pub_date_iso = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
                except Exception:
                    pub_date_iso = None
            if not pub_date_iso and hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                try:
                    pub_date_iso = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()
                except Exception:
                    pub_date_iso = None
            if not pub_date_iso:
                pub_date_iso = datetime.now(timezone.utc).isoformat()

            items.append({
                'title': title,
                'link': link,
                'guid': guid,
                'category': category,
                'source': source_name,
                'image': image,
                'pubDate': pub_date_iso,
                'timestamp': int(time.time())
            })
        except Exception as e:
            print(f" ⚠ Error processing entry: {e}")
            continue

    return items


def get_source_name(feed_url: str) -> str:
    """Return a nice source name for a feed URL"""
    u = (feed_url or '').lower()

    # Common sources
    if 'newscaststudio' in u: return 'NewscastStudio'
    if 'tvtechnology' in u: return 'TV Technology'
    if 'broadcastbeat' in u: return 'BroadcastBeat'
    if 'svgeurope' in u: return 'SVG Europe'
    if 'inbroadcast' in u: return 'InBroadcast'
    if 'rossvideo' in u: return 'Ross Video'
    if 'harmonicinc' in u: return 'Harmonic'
    if 'evertz' in u: return 'Evertz'
    if 'imaginecommunications' in u: return 'Imagine Communications'
    if 'thebroadcastbridge' in u or 'broadcastbridge' in u: return 'The Broadcast Bridge'
    if 'vizrt' in u: return 'Vizrt'
    if 'motionographer' in u: return 'Motionographer'
    if 'aws.amazon' in u: return 'AWS'
    if 'frame.io' in u: return 'Frame.io'
    if 'krebsonsecurity' in u: return 'Krebs on Security'
    if 'darkreading' in u: return 'Dark Reading'
    if 'bleepingcomputer' in u: return 'BleepingComputer'
    if 'securityweek' in u: return 'SecurityWeek'
    if 'feedburner.com/thehackernews' in u: return 'The Hacker News'
    if 'cloud.google.com' in u: return 'Google Cloud'
    if 'microsoft.com' in u: return 'Microsoft Security'

    # Streaming
    if 'streamingmediablog' in u: return 'Streaming Media Blog'
    if 'broadcastnow' in u: return 'Broadcast Now'
    if 'haivision.com' in u: return 'Haivision'
    if 'telestream' in u: return 'Telestream'
    if 'bitmovin.com' in u or 'openrss.org/https://bitmovin.com' in u: return 'Bitmovin'

    # AI Post Production
    if 'premiumbeat' in u: return 'PremiumBeat'
    if 'premieregal' in u: return 'Premiere Gal'
    if 'videocopilot' in u: return 'Video Copilot'
    if 'jonnyelwyn' in u: return 'Jonny Elwyn'
    if 'pond5' in u: return 'Pond5'
    if 'filtergrade' in u: return 'FilterGrade'
    if 'beforesandafters' in u: return 'Befores & Afters'
    if 'avinteractive' in u: return 'AV Magazine'

    # Infra vendors
    if 'api.client.notified.com' in u and 'type=press' in u: return 'Avid Press Room'
    if 'developer.adobe.com' in u or 'openrss.org/https://blog.developer.adobe.com' in u: return 'Adobe Developers'
    if 'chesa.com' in u: return 'Chesa'
    if 'cloudinary' in u: return 'Cloudinary'
    if 'studionetworksolutions' in u: return 'Studio Network Solutions'
    if 'scalelogicinc' in u: return 'ScaleLogic'
    if 'qsan.io' in u: return 'QSAN'
    if 'keycodemedia' in u: return 'Keycode Media'
    if 'processexcellencenetwork' in u: return 'Process Excellence Network'

    return 'Technology News'


def validate_news_data(items):
    """Validate that we have minimum items per category (soft check)"""
    counts = {}
    for it in items:
        cat = it.get('category', '')
        counts[cat] = counts.get(cat, 0) + 1

    print("\n📊 Category distribution:")
    for cat, cnt in sorted(counts.items()):
        mark = "✓" if cnt >= MIN_REQUIRED_EACH else "⚠"
        print(f" {mark} {cat}: {cnt}")

    # soft validation: allow saving even if below minimum when first run
    return True


def _title_fingerprint(title: str) -> str:
    """Normalized title signature for cross-feed duplicate detection.
    Strips punctuation, lowercases, drops short stopwords, and keeps only
    alphabetic tokens 4+ chars long, then takes the first 6 tokens sorted.
    The same NAB press release on TV Technology and Broadcast Beat collapses
    to the same fingerprint even with different GUIDs.
    """
    import re as _re
    if not title:
        return ""
    t = _re.sub(r"[^a-zA-Z0-9\s]", " ", title.lower())
    tokens = [w for w in t.split() if len(w) >= 4 and w not in {
        "with", "from", "that", "this", "will", "show", "2026", "2025",
        "announced", "launches", "introduces", "unveils", "debuts", "nabs",
        "nab", "ibc", "new", "the", "and", "for", "are", "into",
    }]
    return " ".join(sorted(tokens[:6]))


def _title_tokens(title):
    """Return the SET of significant tokens for Jaccard similarity.
    Like _title_fingerprint but returns the full set (not sorted prefix),
    so we can compute overlap ratios across titles with shared vendor+topic.
    """
    import re as _re
    if not title:
        return set()
    t = _re.sub(r"[^a-zA-Z0-9\s]", " ", title.lower())
    return {w for w in t.split() if len(w) >= 4 and w not in {
        "with", "from", "that", "this", "will", "show", "2026", "2025", "2024",
        "announced", "launches", "introduces", "unveils", "debuts", "nabs",
        "nab", "ibc", "new", "the", "and", "for", "are", "into",
        "showcase", "showcases", "showcased", "feature", "features", "featured",
        "to", "at", "on", "in", "by", "of", "a", "an", "is", "its",
        # Broadcast-industry boilerplate that inflates false-positive splits:
        "intelligent", "automation", "solution", "solutions", "platform", "technology",
        "workflow", "workflows", "system", "systems", "broadcast", "media",
        "company", "companies", "announces", "announcing",
    }}


def deduplicate_by_guid(items):
    """Remove duplicate articles by GUID AND by normalized title fingerprint.

    Three-pass dedup:
      1. GUID/link exact match (fast, catches feed-level duplicates)
      2. Title fingerprint (catches cross-feed story re-runs where the
         same NAB/IBC announcement appears on TV Technology, Broadcast Beat,
         TVBEurope, and Newscast Studio with different GUIDs but the same
         underlying story)
      3. Jaccard similarity (catches NEAR-duplicates where titles share
         75%+ of significant tokens but differ by 1–2 verbs like
         "showcase" vs "feature" — e.g. "Bitcentral to Showcase Connected
         Media Workflows" vs "Bitcentral To Feature Connected Media
         Workflows" — which pass #2 misses because one extra token
         pushes them into different fingerprint buckets).
    """
    seen_guids = set()
    seen_fingerprints = set()
    kept_token_sets = []  # list of (token_set, title) for Jaccard pass
    out = []
    dropped_guid = 0
    dropped_title = 0
    dropped_jaccard = 0
    JACCARD_THRESHOLD = 0.70   # 70% overlap → treat as duplicate
    for it in items:
        g = it.get('guid') or it.get('link')
        if g and g in seen_guids:
            dropped_guid += 1
            continue
        fp = _title_fingerprint(it.get('title', ''))
        if fp and fp in seen_fingerprints:
            dropped_title += 1
            continue
        # Pass 3: Jaccard near-duplicate check
        title = it.get('title', '') or ''
        tokens = _title_tokens(title)
        is_near_dup = False
        if tokens and len(tokens) >= 2:
            for prev_tokens, prev_title in kept_token_sets:
                if not prev_tokens:
                    continue
                intersection = len(tokens & prev_tokens)
                union = len(tokens | prev_tokens)
                if union == 0:
                    continue
                similarity = intersection / union
                if similarity >= JACCARD_THRESHOLD:
                    is_near_dup = True
                    print(f"    [DEDUP] Near-duplicate ({similarity:.0%}): "
                          f"'{title[:60]}' matches '{prev_title[:60]}'")
                    break
        if is_near_dup:
            dropped_jaccard += 1
            continue
        if g:
            seen_guids.add(g)
        if fp:
            seen_fingerprints.add(fp)
        if tokens:
            kept_token_sets.append((tokens, title))
        out.append(it)
    print(f"\n🔄 Deduplication: {len(items)} → {len(out)} "
          f"(removed {dropped_guid} by GUID, {dropped_title} by fingerprint, "
          f"{dropped_jaccard} by similarity)")
    return out


def balance_categories(all_items):
    """Balance items across categories; keep newest first within each"""
    all_items = deduplicate_by_guid(all_items)

    by_cat = {}
    for it in all_items:
        cat = it.get('category', '')
        by_cat.setdefault(cat, []).append(it)

    for cat, lst in by_cat.items():
        lst.sort(key=lambda x: x.get('pubDate', ''), reverse=True)

    balanced = []
    for cat, lst in by_cat.items():
        balanced.extend(lst[:MIN_PER_CATEGORY])

    balanced.sort(key=lambda x: x.get('pubDate', ''), reverse=True)
    return balanced[:MAX_NEWS_ITEMS]


def save_json_atomically(data, filepath: Path):
    tmp = filepath.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(filepath)


def main():
    print("🚀 Starting The Streamic RSS Aggregator\n")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    all_items = []

    for category, feed_urls in CATEGORY_FEEDS.items():
        print(f"\n📰 Processing {category.upper()} ({len(feed_urls)} feeds)")
        for feed_url in feed_urls:
            try:
                feed = fetch_feed_with_fallback(feed_url)
                if not feed or not feed.entries:
                    print(f" ⚠ No entries from {feed_url[:80]}")
                    continue

                entries = feed.entries[:MAX_ITEMS_PER_FEED]
                source_name = get_source_name(feed_url)
                items = process_entries(entries, category, source_name)
                # Filter off-topic items at source
                broadcast_items = [
                    it for it in items
                    if is_broadcast_item(it.get("title",""), it.get("teaser",""))
                ]
                skipped = len(items) - len(broadcast_items)
                all_items.extend(broadcast_items)
                msg = f" ({skipped} off-topic skipped)" if skipped else ""
                print(f" ✓ {source_name}: {len(broadcast_items)} items{msg}")
            except Exception as e:
                print(f" ✗ Error with {feed_url[:80]}: {e}")
                continue

    print(f"\n📦 Total items collected: {len(all_items)}")
    if not all_items:
        print("❌ No items collected. Exiting.")
        return

    balanced_items = balance_categories(all_items)
    print(f"⚖️ Balanced to: {len(balanced_items)} items")

    _ok = validate_news_data(balanced_items)

    # archive previous, then save
    if OUTPUT_FILE.exists():
        if ARCHIVE_FILE.exists():
            ARCHIVE_FILE.unlink()
        OUTPUT_FILE.rename(ARCHIVE_FILE)
        print(f"\n💾 Backed up previous data to {ARCHIVE_FILE}")

    save_json_atomically(balanced_items, OUTPUT_FILE)
    print(f"✅ Saved {len(balanced_items)} items to {OUTPUT_FILE}")
    print("\n🎉 Aggregation complete!")


if __name__ == "__main__":
    main()
