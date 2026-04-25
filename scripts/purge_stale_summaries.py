#!/usr/bin/env python3
"""
purge_stale_summaries.py  —  one-shot cleanup of legacy summary cache

Why this exists
---------------
Prior to the October 2025 premium-pipeline upgrade, data/summaries/<slug>.json
files were written in an older schema that lacks `generated_by`, `quality_score`,
and `generated_at`. They also typically hold 400–700 word scaffold bodies
without the required <h2> section structure.

Those stale files defeat the new generate_gemini.py logic in two ways:
  1. needs_gemini_processing() correctly flags them as thin_content, but if
     Gemini quota runs out mid-run, the stale file remains and
     patch_generated_articles() copies its thin body straight back into
     generated_articles.json — the exact homepage regression we're fixing.
  2. On a fresh run, build.py renders the stale body before Gemini even
     gets a chance to upgrade it.

What this script does
---------------------
Deletes ONLY summary files that match any of the staleness tests:
  • missing `generated_by` key (pre-upgrade schema)
  • word_count < 800 (below the new quality floor)
  • body_html does not contain <h2 (no structured sections)
  • unparseable JSON

Gemini 2.5-Pro outputs that already meet the quality bar are untouched.
After running this, generate_gemini.py will see these slugs as "no_summary"
and regenerate them cleanly using the current deep-dive prompt.

Usage
-----
    python scripts/purge_stale_summaries.py         # live purge
    python scripts/purge_stale_summaries.py --dry   # report only, no deletes

Safe to re-run. Idempotent.
"""
import json
import os
import sys
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARIES_DIR = os.path.join(ROOT, "data", "summaries")

DRY_RUN = "--dry" in sys.argv or "-n" in sys.argv


def is_stale(path: str) -> tuple:
    """Return (stale: bool, reason: str)."""
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
    except Exception as e:
        return True, f"unparseable_json ({type(e).__name__})"

    if not s.get("generated_by"):
        return True, "missing_generated_by (pre-upgrade schema)"

    wc = s.get("word_count", 0)
    if wc < 800:
        return True, f"thin_content_{wc}w"

    body = s.get("body_html") or ""
    if "<h2" not in body:
        return True, "no_h2_structure"

    return False, f"ok ({wc}w, {s.get('generated_by')})"


def main():
    if not os.path.isdir(SUMMARIES_DIR):
        print(f"✗ Summaries directory not found: {SUMMARIES_DIR}")
        sys.exit(1)

    files = sorted(glob.glob(os.path.join(SUMMARIES_DIR, "*.json")))
    if not files:
        print("No summary files found. Nothing to do.")
        return

    mode = "DRY RUN" if DRY_RUN else "LIVE"
    print(f"purge_stale_summaries [{mode}]")
    print(f"  scanning {len(files)} files in {SUMMARIES_DIR}")
    print()

    removed = 0
    kept = 0
    for fp in files:
        stale, reason = is_stale(fp)
        name = os.path.basename(fp)
        if stale:
            if DRY_RUN:
                print(f"  WOULD REMOVE  {name}  — {reason}")
            else:
                try:
                    os.remove(fp)
                    print(f"  REMOVED  {name}  — {reason}")
                except Exception as e:
                    print(f"  ✗ failed to remove {name}: {e}")
                    continue
            removed += 1
        else:
            kept += 1

    print()
    print(f"Summary: removed={removed}  kept={kept}  total={len(files)}")
    if DRY_RUN and removed:
        print("Re-run without --dry to apply.")


if __name__ == "__main__":
    main()
