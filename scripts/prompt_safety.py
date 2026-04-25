"""
prompt_safety.py — Single source of truth for factual-safety rules.

Every generator in this repo (generate_mistral.py, generate_summaries.py,
generate_editorial.py, generate_gemini.py, generate_openrouter.py,
generate_vendor_hub.py) imports FACTUAL_SAFETY_BLOCK from here and
prepends it to its own system prompt. This guarantees that vendor
misclassifications, invented standards support, and hype language are
forbidden uniformly across every AI generation path.

HEADING LEVEL:
  The factual_safety.txt file uses {H} as a placeholder for the chosen
  section heading level. This loader substitutes it at import time based
  on the STREAMIC_HEADING_LEVEL environment variable.

    STREAMIC_HEADING_LEVEL=h3  (default) — Apple Premium / Awwwards magazine
                                           style with small all-caps section
                                           headers
    STREAMIC_HEADING_LEVEL=h2             — traditional trade-journal style
                                           with larger serif section headers

  The <h3>Sources</h3> terminal block is ALWAYS h3 regardless of this
  setting — it's a reference section, not a content section.

If you need to update the safety rules (e.g. add a new vendor to the safe
list, ban a new phrase), edit scripts/factual_safety.txt only. All
generators pick up the change on the next run.
"""
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SAFETY_FILE = os.path.join(_THIS_DIR, "factual_safety.txt")

# Allowed heading levels — normalise lowercase, reject anything else to
# prevent prompt injection via env variable
_ALLOWED_HEADINGS = {"h2", "h3"}
HEADING_LEVEL = os.environ.get("STREAMIC_HEADING_LEVEL", "h3").strip().lower()
if HEADING_LEVEL not in _ALLOWED_HEADINGS:
    HEADING_LEVEL = "h3"


def _load() -> str:
    try:
        with open(_SAFETY_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        # Substitute {H} placeholder with the chosen heading tag.
        # This lets one factual_safety.txt serve both H2 and H3 modes
        # without duplicating prompt text.
        return raw.replace("{H}", HEADING_LEVEL)
    except Exception:
        # Minimal fallback if the file is missing — never crash a pipeline
        return (
            "STRICT FACTUAL SAFETY: Never guess what a product does. Never "
            "assign a product category unless the source explicitly states it. "
            "Never invent standards support (ST 2110, NMOS, SCTE-35, etc.) "
            "unless the source names them. Never add competitor names not in "
            "the source. Mediagenix is scheduling/rights/BMS — NOT playout. "
            "If the source is vague, stay vague. Accuracy over impressiveness."
        )


FACTUAL_SAFETY_BLOCK = _load()
