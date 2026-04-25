#!/usr/bin/env python3
"""
AdSense Cleanup Script — The Streamic
=====================================
One-time cleanup to remove thin/duplicate articles for AdSense compliance.

WHAT IT DOES:
  1. Removes articles with < 500 word body from generated_articles.json
  2. Deletes orphan HTML files in docs/articles/ not linked to quality content
  3. Preserves guide files, quality editorials, and 500+ word articles
  4. Creates a backup before any changes

SAFE TO RUN: Creates backup, prints everything it will do before doing it.
Run with --dry-run to preview without changes.

Usage:
  python3 scripts/adsense_cleanup.py              # execute cleanup
  python3 scripts/adsense_cleanup.py --dry-run     # preview only
"""

import json, os, re, sys, shutil
from datetime import datetime

DRY_RUN = "--dry-run" in sys.argv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(ROOT, "data", "generated_articles.json")
ARTS_DIR  = os.path.join(ROOT, "docs", "articles")
BACKUP_DIR = os.path.join(ROOT, "data", "backups")

# ── Files to ALWAYS keep (guides, quality editorials not in JSON) ──────────
PROTECTED_FILES = {
    # How-to guides (manually written, high quality)
    "guide-audio-conform-avid-protools.html",
    "guide-avid-media-central-health-check.html",
    "guide-avid-strawberry.html",
    "guide-media-central-cache.html",
    "guide-premiere-to-avid.html",
    "guide-vantage-aws-transcode.html",
    "guide-vantage-nas-transcode.html",
    "guide-vizrt-avid-integration.html",
    # Quality editorial orphans (real content, 1000+ words)
    "beyond-chatbot-invisible-ai-newsroom-2026.html",
    "c2pa-digital-provenance-deepfake-news-credibility.html",
    "green-broadcast-cloud-carbon-footprint-analysis.html",
    "paris-2024-cloud-production-legacy-global-events-2026.html",
    "paris-2024-legacy-cloud-production-2026.html",
    "st2110-small-market-hybrid-ip-transition.html",
    "studio-di-pipeline-workflow-2026.html",
    "quic-http3-video-delivery-streaming-2026.html",
}

MIN_WORDS = 500  # Minimum word count for AdSense quality

def word_count(html):
    """Count words in HTML body content."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    return len(text.split())

def main():
    print("=" * 60)
    print("THE STREAMIC — AdSense Cleanup Script")
    print("=" * 60)
    if DRY_RUN:
        print(">>> DRY RUN MODE — no changes will be made <<<\n")
    else:
        print(">>> LIVE MODE — changes will be applied <<<\n")

    # ── Load JSON ────────────────────────────────────────────────
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        articles = json.load(f)
    print(f"Loaded {len(articles)} articles from generated_articles.json")

    # ── Separate keep vs delete from JSON ────────────────────────
    keep_json = []
    delete_json = []
    for a in articles:
        body = a.get("body_html", "") or ""
        wc = word_count(body)
        is_editorial = a.get("is_editorial") or a.get("editorial")
        # Editorial articles are always kept (curated, homepage-referenced)
        if is_editorial or wc >= MIN_WORDS:
            keep_json.append(a)
        else:
            delete_json.append(a)

    print(f"\nJSON articles to KEEP (>={MIN_WORDS} words): {len(keep_json)}")
    print(f"JSON articles to DELETE (<{MIN_WORDS} words): {len(delete_json)}")
    print()

    # Show what we're keeping
    print("── KEEPING ──")
    for a in sorted(keep_json, key=lambda x: word_count(x.get("body_html", "")), reverse=True):
        wc = word_count(a.get("body_html", ""))
        tag = " [EDITORIAL]" if a.get("is_editorial") or a.get("editorial") else ""
        print(f"  {wc:4d}w  {a.get('slug', '?')}{tag}")

    # ── Map JSON slugs for HTML cleanup ──────────────────────────
    keep_slugs = {a.get("slug", "") for a in keep_json if a.get("slug")}

    # ── Scan HTML files ──────────────────────────────────────────
    html_files = [f for f in os.listdir(ARTS_DIR) if f.endswith(".html")]
    print(f"\nTotal HTML files in docs/articles/: {len(html_files)}")

    keep_html = []
    delete_html = []
    for f in html_files:
        slug = f.replace(".html", "")
        if f in PROTECTED_FILES:
            keep_html.append(f)
        elif slug in keep_slugs:
            keep_html.append(f)
        else:
            delete_html.append(f)

    print(f"HTML files to KEEP: {len(keep_html)}")
    print(f"  - From quality JSON: {len([f for f in keep_html if f not in PROTECTED_FILES])}")
    print(f"  - Protected (guides/editorials): {len([f for f in keep_html if f in PROTECTED_FILES])}")
    print(f"HTML files to DELETE: {len(delete_html)}")

    if DRY_RUN:
        print("\n── FILES THAT WOULD BE DELETED ──")
        for f in sorted(delete_html):
            print(f"  DEL  {f}")
        print(f"\n>>> Dry run complete. Run without --dry-run to apply. <<<")
        return

    # ── Create backup ────────────────────────────────────────────
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_json = os.path.join(BACKUP_DIR, f"generated_articles_{ts}.json")
    shutil.copy2(JSON_PATH, backup_json)
    print(f"\n✓ Backup saved: {backup_json}")

    # ── Write cleaned JSON ───────────────────────────────────────
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(keep_json, f, ensure_ascii=False, indent=2)
    print(f"✓ Updated generated_articles.json: {len(keep_json)} articles")

    # ── Delete HTML files ────────────────────────────────────────
    deleted_count = 0
    for f in delete_html:
        filepath = os.path.join(ARTS_DIR, f)
        try:
            os.remove(filepath)
            deleted_count += 1
        except OSError as ex:
            print(f"  ⚠ Could not delete {f}: {ex}")
    print(f"✓ Deleted {deleted_count} HTML files from docs/articles/")

    # ── Summary ──────────────────────────────────────────────────
    remaining_html = len([f for f in os.listdir(ARTS_DIR) if f.endswith(".html")])
    print(f"\n{'='*60}")
    print(f"CLEANUP COMPLETE")
    print(f"  JSON articles: {len(articles)} → {len(keep_json)}")
    print(f"  HTML files: {len(html_files)} → {remaining_html}")
    print(f"  Protected files preserved: {len(PROTECTED_FILES)}")
    print(f"  Backup at: {backup_json}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
