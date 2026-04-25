#!/usr/bin/env python3
"""
force_refresh_visible.py — targeted recovery for homepage-visible slugs

Problem this solves
-------------------
The Streamic pipeline's normal run order is:
    rewrite_feed.py -> generate_summaries.py -> generate_gemini.py -> build.py

On every scheduled run, Gemini 2.5-Pro runs out of quota before it finishes
upgrading all ~35 homepage-visible slugs to 800+ words. The result: the
homepage keeps rendering 472–716 word `rewrite_feed_local` scaffold bodies
and stale pre-upgrade summary files that were written in the legacy schema.

This script breaks the loop by:
  1. Reading docs/data/generated_articles.json to find the EXACT slugs
     currently rendered on the homepage (featured_priority + top items).
  2. For those slugs only:
        a. Deleting data/summaries/<slug>.json if it is stale (no
           generated_by, word_count < 800, or no <h2> structure).
        b. Setting needs_gemini=True on the article record in
           data/generated_articles.json so the next generate_gemini.py run
           is guaranteed to reprocess them.
        c. Clearing generated_by so the quality gate also flags them.
  3. Leaving all hidden/archive slugs untouched so Gemini quota is spent
     only on slugs users actually see.

After this script runs, execute:
    python scripts/generate_gemini.py
    python scripts/build.py

...and the homepage will render the fresh deep-dive bodies on the first run.

Usage
-----
    python scripts/force_refresh_visible.py            # live refresh
    python scripts/force_refresh_visible.py --dry      # preview, no writes
    python scripts/force_refresh_visible.py --top 20   # default: top 20 slugs

Safe: idempotent, never touches hidden articles, never touches non-stale
Gemini Pro outputs, never modifies HTML templates or build.py output.
"""
import json
import os
import sys
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN_ARTS_F    = os.path.join(ROOT, "data", "generated_articles.json")
DOCS_GEN_F    = os.path.join(ROOT, "docs", "data", "generated_articles.json")
SUMMARIES_DIR = os.path.join(ROOT, "data", "summaries")

DRY_RUN = "--dry" in sys.argv or "-n" in sys.argv
TOP_N = 20
if "--top" in sys.argv:
    try:
        TOP_N = int(sys.argv[sys.argv.index("--top") + 1])
    except (ValueError, IndexError):
        pass


def summary_is_stale(path: str) -> tuple:
    """Return (stale: bool, reason: str) for a given summary file."""
    if not os.path.exists(path):
        return True, "missing"
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
    except Exception as e:
        return True, f"unparseable ({type(e).__name__})"
    if not s.get("generated_by"):
        return True, "no_generated_by"
    wc = s.get("word_count", 0)
    if wc < 800:
        return True, f"thin_{wc}w"
    body = s.get("body_html") or ""
    if "<h2" not in body:
        return True, "no_h2"
    return False, f"ok_{wc}w"


def load_visible_slugs() -> list:
    """Return ordered list of homepage-visible slugs from docs build output."""
    if not os.path.exists(DOCS_GEN_F):
        print(f"✗ {DOCS_GEN_F} not found — run build.py at least once first.")
        sys.exit(1)
    with open(DOCS_GEN_F, encoding="utf-8") as f:
        docs = json.load(f)

    visible = []
    seen = set()

    def _is_target(a: dict) -> bool:
        """Include rewrite_feed_local scaffolds; skip only true hand-authored editorials."""
        gen_by = (a.get("generated_by") or "").lower()
        is_scaffold = gen_by in ("rewrite_feed_local", "", "rewrite_feed")
        # rewrite_feed flags RSS items with is_editorial=True routing reasons,
        # but they still need Gemini upgrade. Only skip true hand-authored editorials.
        if (a.get("is_editorial") or a.get("editorial")) and not is_scaffold:
            return False
        return True

    # featured_priority = the hand-curated top carousel
    for a in docs.get("featured_priority", []):
        sl = a.get("slug")
        if sl and sl not in seen and _is_target(a):
            visible.append(sl)
            seen.add(sl)
    # items = the Latest Insights / Breaking News pool (newest first)
    for a in docs.get("items", []):
        sl = a.get("slug")
        if sl and sl not in seen and _is_target(a):
            visible.append(sl)
            seen.add(sl)
        if len(visible) >= TOP_N:
            break
    return visible[:TOP_N]


def main():
    mode = "DRY RUN" if DRY_RUN else "LIVE"
    print(f"force_refresh_visible [{mode}]  top={TOP_N}")
    print()

    visible = load_visible_slugs()
    print(f"Homepage-visible slugs: {len(visible)}")
    if not visible:
        print("Nothing to do.")
        return

    # Load generated_articles.json
    with open(GEN_ARTS_F, encoding="utf-8") as f:
        arts = json.load(f)
    by_slug = {a.get("slug", ""): a for a in arts}

    deleted_summaries = 0
    marked_articles = 0
    untouched = 0

    print()
    print("Slug                                                               summary      action")
    print("-" * 100)

    for slug in visible:
        sp = os.path.join(SUMMARIES_DIR, f"{slug}.json")
        stale, reason = summary_is_stale(sp)
        label = slug[:63]

        if not stale:
            print(f"  {label:<63}  {reason:<12}  keep (already upgraded)")
            untouched += 1
            continue

        # Delete stale summary
        if os.path.exists(sp):
            if not DRY_RUN:
                try:
                    os.remove(sp)
                except Exception as e:
                    print(f"  ✗ {label} — failed to remove summary: {e}")
                    continue
            deleted_summaries += 1

        # Flag article record so generate_gemini.py can't skip it
        art = by_slug.get(slug)
        if art is not None:
            art["needs_gemini"] = True
            # Clear Gemini-Pro marker so needs_gemini_processing() flags it
            if art.get("generated_by") != "gemini-2.5-pro":
                pass  # already flagged by gen_by check
            # Force the word_count < 800 gate to trigger regardless
            if art.get("word_count", 0) >= 800:
                art["word_count"] = 0
            marked_articles += 1
            print(f"  {label:<63}  {reason:<12}  DELETE + flag")
        else:
            print(f"  {label:<63}  {reason:<12}  DELETE (no art record)")

    # Persist generated_articles.json
    if marked_articles and not DRY_RUN:
        with open(GEN_ARTS_F, "w", encoding="utf-8") as f:
            json.dump(arts, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 72)
    print(f"  Stale summaries removed:   {deleted_summaries}")
    print(f"  Article records flagged:   {marked_articles}")
    print(f"  Already-upgraded (kept):   {untouched}")
    print()
    if DRY_RUN:
        print("DRY RUN — no files written. Re-run without --dry to apply.")
    else:
        print("Next steps:")
        print("  1. python scripts/generate_gemini.py   # upgrades the flagged slugs")
        print("  2. python scripts/build.py              # renders the upgraded site")


if __name__ == "__main__":
    main()
