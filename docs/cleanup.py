#!/usr/bin/env python3
"""
cleanup.py — The Streamic: RSS / AI content purge
===================================================

Purges every RSS-origin and AI-generated article from the content store,
keeping ONLY content you wrote (or curated) by hand.

KEEP rules (an article survives if ANY of these is true)
--------------------------------------------------------
  K1.  generated_by == "gpt_manual_editorial"
       → your hand-curated NAB deep-dives (15 articles).

  K2.  source_domain in {"", "thestreamic.in"}  AND  generated_by is None
       → your hand-written originals (guides, pillars, Expertinsight).
       The empty-domain check catches files authored without a domain;
       "thestreamic.in" catches ones you tagged as your own.

  K3.  HTML file exists under articles/<slug>.html or docs/articles/<slug>.html
       and starts with `<!-- HAND_AUTHORED -->`
       → immutable manual override (belt-and-braces).

  K4.  slug ∈ PROTECTED_SLUGS (hard-coded exceptions you control below).

Everything else is DELETED from generated_articles.json plus its HTML
output under docs/articles/<slug>.html.

WHAT ELSE THIS SCRIPT CLEANS
----------------------------
  • data/news.json        → emptied to []   (RSS feed cache, not needed)
  • data/archive.json     → emptied to []   (RSS archive, not needed)
  • data/hf_articles.json → emptied to []   (BroadcastBeat/AWS RSS cache)
  • data/summaries/       → removed         (AI-summary cache)

The script is IDEMPOTENT and DRY-RUN by default.  Pass --execute to commit.

Usage
-----
    python3 cleanup.py              # dry-run, prints what would be removed
    python3 cleanup.py --execute    # actually delete
    python3 cleanup.py --execute --no-backup   # skip .bak files

Run from the repo root.  Writes to ./data/ and ./docs/articles/.
"""

from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = os.path.abspath(os.path.dirname(__file__))

# Repository paths — resolved relative to this script's location
DATA_DIR      = os.path.join(ROOT, "data")
DOCS_DIR      = os.path.join(ROOT, "docs")
DOCS_ARTS_DIR = os.path.join(DOCS_DIR, "articles")
ROOT_ARTS_DIR = os.path.join(ROOT, "articles")  # checked for HAND_AUTHORED

GENERATED_ARTICLES_JSON = os.path.join(DATA_DIR, "generated_articles.json")
NEWS_JSON               = os.path.join(DATA_DIR, "news.json")
ARCHIVE_JSON            = os.path.join(DATA_DIR, "archive.json")
HF_ARTICLES_JSON        = os.path.join(DATA_DIR, "hf_articles.json")
SUMMARIES_DIR           = os.path.join(DATA_DIR, "summaries")

# ── Keep-rule domains ─────────────────────────────────────────────────────────
#   Any article whose source_domain is in this set AND has no AI generator
#   tag is treated as hand-authored.
OWN_DOMAINS = {"", "thestreamic.in"}

# ── Manual-editorial flag values (hand-curated content always kept) ───────────
MANUAL_GENERATORS = {"gpt_manual_editorial"}

# ── Hard-coded exceptions ─────────────────────────────────────────────────────
#   Slugs here are ALWAYS kept, regardless of metadata.
#   Use this for anything that slipped through the origin tagging.
#   Sourced from build.py HOMEPAGE_PROTECTED_SLUGS plus your guide/pillar set.
PROTECTED_SLUGS = {
    # Homepage hero & pillars (from build.py)
    "ai-reducing-broadcast-operational-costs-2026",
    "broadcast-automation-systems-guide-2026",
    "ip-broadcasting-smpte-st2110-engineering-guide-2026",
    "cloud-broadcast-workflows-remote-production-2026",
    "media-asset-management-ai-era-monetisation-2026",
    "beyond-the-chatbot-operational-ai-newsroom-2026",
    "st-2110-small-market-hybrid-ip-broadcasters-2026",
    "paris-2024-cloud-production-legacy-global-events-2026",
    "c2pa-deepfake-news-credibility-digital-provenance-2026",
    "studio-grade-video-workflow-post-production-2026",
    "green-broadcast-cloud-carbon-footprint-sustainability-2026",
    # Additional pillars visible in data with domain="thestreamic.in"
    "future-of-ai-in-broadcast-deployment-2026",
    "ai-video-post-production-editing-vfx-automation-2026",
    "live-production-ai-automation-real-time-broadcasting-2026",
    "ip-transition-2026-practical-guide-broadcast-engineers",
    "cloud-playout-economics-2026-build-vs-buy",
    # Guides and Expert Insight (file-only, may not appear in JSON)
    "Expertinsight1",
    "nab-2026-hybrid-technology-year",
    "deepdive-pebble-harmonic-playout-war-nab-2026",
    "deepdive-aws-google-cloud-agentic-ai-nab-2026",
    "guide-audio-conform-avid-protools",
    "guide-avid-media-central-health-check",
    "guide-avid-strawberry",
    "guide-media-central-cache",
    "guide-premiere-to-avid",
    "guide-vantage-aws-transcode",
    "guide-vantage-nas-transcode",
    "guide-vizrt-avid-integration",
    "telestream-adobe-vantage-premiere-workflow-integration-2026",
}


# ══════════════════════════════════════════════════════════════════════════════
# Classification
# ══════════════════════════════════════════════════════════════════════════════

def _read_hand_authored_marker(slug: str) -> bool:
    """Return True if <!-- HAND_AUTHORED --> appears in the first 400 bytes
    of any HTML file (root articles/ or docs/articles/) for this slug."""
    if not slug:
        return False
    for base in (ROOT_ARTS_DIR, DOCS_ARTS_DIR):
        fp = os.path.join(base, f"{slug}.html")
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                if "HAND_AUTHORED" in fh.read(400):
                    return True
        except OSError:
            continue
    return False


def is_keep(article: dict[str, Any]) -> tuple[bool, str]:
    """Decide whether an article in generated_articles.json is hand-authored.

    Returns (keep: bool, reason: str). Reason is for audit logging.
    """
    slug = (article.get("slug") or "").strip()

    # K4 — explicit protected list (always first, never ambiguous)
    if slug in PROTECTED_SLUGS:
        return True, "protected-slug"

    # K1 — manual editorial flag
    gen_by = (article.get("generated_by") or "").strip()
    if gen_by in MANUAL_GENERATORS:
        return True, f"manual-generator={gen_by}"

    # K3 — file-level HAND_AUTHORED marker
    if _read_hand_authored_marker(slug):
        return True, "file-marker=HAND_AUTHORED"

    # K2 — own-domain + no AI generator
    domain = (article.get("source_domain") or "").strip()
    if domain in OWN_DOMAINS and not gen_by:
        return True, f"own-domain={domain or 'empty'}, no-generator"

    # Everything else is purged
    reason_parts = []
    if gen_by:
        reason_parts.append(f"generated_by={gen_by}")
    if domain and domain not in OWN_DOMAINS:
        reason_parts.append(f"external={domain}")
    return False, ", ".join(reason_parts) or "unclassified-rss"


# ══════════════════════════════════════════════════════════════════════════════
# File ops
# ══════════════════════════════════════════════════════════════════════════════

def _backup(path: str) -> None:
    if not os.path.exists(path):
        return
    bak = path + ".bak"
    shutil.copy2(path, bak)
    print(f"    ↳ backup: {os.path.relpath(bak, ROOT)}")


def _remove_file(path: str, *, execute: bool) -> bool:
    if not os.path.exists(path):
        return False
    if execute:
        os.remove(path)
    return True


def _write_json(path: str, data: Any, *, execute: bool) -> None:
    if not execute:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# Orchestration
# ══════════════════════════════════════════════════════════════════════════════

def purge_generated_articles(*, execute: bool, backup: bool) -> tuple[list, list]:
    """Split generated_articles.json into (kept, purged). Returns both lists."""
    if not os.path.exists(GENERATED_ARTICLES_JSON):
        print(f"  ⚠ {GENERATED_ARTICLES_JSON} not found — skipping")
        return [], []

    with open(GENERATED_ARTICLES_JSON, "r", encoding="utf-8") as f:
        all_arts = json.load(f)

    if not isinstance(all_arts, list):
        print("  ✗ generated_articles.json root is not a list — aborting")
        sys.exit(1)

    kept, purged = [], []
    for art in all_arts:
        keep, reason = is_keep(art)
        if keep:
            kept.append((art, reason))
        else:
            purged.append((art, reason))

    print(f"\n  ▸ Scanned {len(all_arts)} articles")
    print(f"    KEEP:  {len(kept)}")
    print(f"    PURGE: {len(purged)}")

    # Audit: show kept reasons (so you can eyeball it before --execute)
    print("\n  ── KEEP (first 25) ────────────────────────────────")
    for art, reason in kept[:25]:
        slug = (art.get("slug") or "?")[:60]
        print(f"    ✓ {slug:<62} [{reason}]")
    if len(kept) > 25:
        print(f"    … and {len(kept) - 25} more kept")

    # Audit: show a sample of purge reasons
    print("\n  ── PURGE (first 15) ───────────────────────────────")
    for art, reason in purged[:15]:
        slug = (art.get("slug") or "?")[:60]
        print(f"    ✗ {slug:<62} [{reason}]")
    if len(purged) > 15:
        print(f"    … and {len(purged) - 15} more purged")

    if execute:
        if backup:
            _backup(GENERATED_ARTICLES_JSON)
        keepers = [a for a, _ in kept]
        _write_json(GENERATED_ARTICLES_JSON, keepers, execute=True)
        print(f"\n  ✓ Rewrote generated_articles.json ({len(keepers)} articles)")

    return [a for a, _ in kept], [a for a, _ in purged]


def purge_html_files(purged_slugs: set[str], *, execute: bool) -> int:
    """Delete docs/articles/<slug>.html for every purged slug.

    Never touches ROOT_ARTS_DIR (that's your source-of-truth for any
    file-only hand-authored content).
    """
    if not os.path.isdir(DOCS_ARTS_DIR):
        print(f"  ⚠ {DOCS_ARTS_DIR} not found — skipping HTML cleanup")
        return 0

    removed = 0
    skipped_protected = 0
    for fname in sorted(os.listdir(DOCS_ARTS_DIR)):
        if not fname.endswith(".html"):
            continue
        slug = fname[:-5]

        # Never delete files we hand-protected (they may have been
        # manually authored directly into docs/ without a JSON entry).
        if slug in PROTECTED_SLUGS:
            skipped_protected += 1
            continue

        # Don't delete files for slugs we kept in the JSON either
        if slug not in purged_slugs:
            continue

        # Don't delete if the file itself carries HAND_AUTHORED
        if _read_hand_authored_marker(slug):
            continue

        fp = os.path.join(DOCS_ARTS_DIR, fname)
        if _remove_file(fp, execute=execute):
            removed += 1

    print(f"\n  ▸ HTML cleanup: {removed} file(s) {'removed' if execute else 'WOULD be removed'}"
          f" (protected skipped: {skipped_protected})")
    return removed


def purge_rss_caches(*, execute: bool, backup: bool) -> None:
    """Empty the RSS/AI auxiliary caches. They're no longer populated by
    the workflow and keeping stale copies risks leakage into the build."""
    for path in (NEWS_JSON, ARCHIVE_JSON, HF_ARTICLES_JSON):
        if not os.path.exists(path):
            continue
        label = os.path.relpath(path, ROOT)
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            count = len(existing) if hasattr(existing, "__len__") else "?"
        except Exception:
            count = "?"
        print(f"    {label}: {count} entries → []")
        if execute:
            if backup:
                _backup(path)
            _write_json(path, [], execute=True)

    if os.path.isdir(SUMMARIES_DIR):
        entries = [e for e in os.listdir(SUMMARIES_DIR) if not e.startswith(".")]
        print(f"    data/summaries/: {len(entries)} file(s) → {'removed' if execute else 'WOULD be removed'}")
        if execute:
            shutil.rmtree(SUMMARIES_DIR)
            os.makedirs(SUMMARIES_DIR, exist_ok=True)  # keep the folder present


def write_audit_log(kept: list, purged: list, *, execute: bool) -> None:
    """Drop a timestamped audit log next to data/ so you have a receipt."""
    if not execute:
        return
    log_path = os.path.join(ROOT, "cleanup-audit.log")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n=== cleanup.py run @ {ts} ===\n")
        f.write(f"KEPT   ({len(kept)}):\n")
        for a in kept:
            f.write(f"  {a.get('slug','?')}\n")
        f.write(f"PURGED ({len(purged)}):\n")
        for a in purged:
            f.write(f"  {a.get('slug','?')}  [source_domain={a.get('source_domain','')}, gen={a.get('generated_by','')}]\n")
    print(f"  ✓ Audit log appended: cleanup-audit.log")


# ══════════════════════════════════════════════════════════════════════════════
# Entry
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Purge RSS/AI content from The Streamic.")
    parser.add_argument("--execute", action="store_true",
                        help="Actually delete files. Without this flag, dry-run only.")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip writing .bak copies before overwriting JSON files.")
    parser.add_argument("--skip-caches", action="store_true",
                        help="Don't touch news.json / archive.json / hf_articles.json / summaries/.")
    args = parser.parse_args()

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print("═" * 72)
    print(f"  The Streamic — content purge  ({mode})")
    print("═" * 72)

    print("\n[1/3] Purging generated_articles.json …")
    kept, purged = purge_generated_articles(
        execute=args.execute, backup=not args.no_backup,
    )

    print("\n[2/3] Purging rendered HTML under docs/articles/ …")
    purged_slugs = {a.get("slug") for a in purged if a.get("slug")}
    purge_html_files(purged_slugs, execute=args.execute)

    if not args.skip_caches:
        print("\n[3/3] Clearing RSS/AI caches …")
        purge_rss_caches(execute=args.execute, backup=not args.no_backup)
    else:
        print("\n[3/3] Skipped cache cleanup (--skip-caches)")

    write_audit_log(kept, purged, execute=args.execute)

    print("\n" + "═" * 72)
    if args.execute:
        print("  ✅ Cleanup complete.")
        print("  Next step: run `python3 build.py` — it will regenerate")
        print("  docs/sitemap.xml from the remaining articles automatically.")
    else:
        print("  🔍 Dry-run complete. Re-run with --execute to commit changes.")
    print("═" * 72)


if __name__ == "__main__":
    main()
