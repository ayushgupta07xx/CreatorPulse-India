"""Stage-0 brief query-expansion + results explainer for the match engine.

expand_brief(): Groq disambiguates a short/polysemous brand brief toward the
creator-economy sense ("roasting" -> comedy roast, not cooking) and appends
concrete creator-content phrases, so BGE-small embeds it richly. It is ADDITIVE
(original brief is preserved) and NO-OPS to the raw brief when GROQ_API_KEY is
unset or the call fails/times out -- offline + CI stay green, a match never
blocks on the LLM. Reuses Groq via requests (no new dependency). (ADR-0026)

explain_results(): deterministic "why no/few results" from the match funnel
counts -- a reviewer-trustable diagnostic, not an LLM guess.

Smoke:  set -a; source .env; set +a; python -m apps.ml.query_expand "roasting"
"""

from __future__ import annotations

import logging
import os

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
_TIMEOUT = 8

_SYSTEM = (
    "You expand a brand's influencer-marketing brief into search keywords for "
    "matching YouTube creators. Resolve ambiguous words toward the creator / "
    "entertainment sense, never the literal one: 'roasting' = comedy roast / "
    "insult comedy (not cooking); 'reaction' = reaction videos; 'GRWM' = beauty "
    "get-ready-with-me. Add 4-8 concrete creator-content phrases (niches, "
    "formats, content styles) that a matching creator's channel text would "
    "contain. Output ONLY a comma-separated list of phrases. No preamble, no "
    "numbering, no explanation."
)

_log = logging.getLogger(__name__)


def expand_brief(brief: str, *, model: str | None = None, timeout: int = _TIMEOUT) -> str:
    """Return ``brief`` enriched with disambiguated creator-content terms.

    No-ops (returns ``brief`` unchanged) without a key or on any failure.
    """
    key = os.environ.get("GROQ_API_KEY")
    if not key or not brief.strip():
        return brief
    model = model or os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    try:
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": brief.strip()},
                ],
                "temperature": 0.2,
                "max_tokens": 120,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        terms = r.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - network / 429 / parse all degrade
        _log.warning("query expansion no-op (%s); using raw brief", exc)
        return brief
    terms = " ".join(str(terms).split()).strip(" .,")
    if not terms:
        return brief
    return f"{brief.strip()}, {terms}"


def explain_results(funnel: dict) -> str | None:
    """Deterministic 'why no / few results' from match() funnel counts.

    Returns None when results came back fine.
    """
    if funnel.get("returned", 0):
        return None
    niche = funnel.get("niche_filter")
    after_niche = funnel.get("after_niche", 0)
    after_floor = funnel.get("after_floor", 0)
    top_cos = funnel.get("top_cosine", 0.0)
    min_views = funnel.get("min_views", 0.0)
    if niche and after_niche == 0:
        return (
            f"No creators in the '{niche}' niche cleared search. That niche has "
            "thin coverage in the catalog - broaden the niche or drop the filter."
        )
    if after_floor == 0 and after_niche > 0:
        return (
            f"{after_niche} creators matched the brief but all fell below the "
            f"reach floor (min_views={min_views:.0f}). Lower the floor or raise "
            "the budget."
        )
    if top_cos < 0.30:
        return (
            "The brief embedded weakly - it's short or broadly worded. Add "
            "specific niche/format terms (e.g. 'comedy roast videos', not just "
            "'roasting')."
        )
    return (
        "No strong matches for this brief. Try rephrasing with the creator niche "
        "and the content format."
    )


if __name__ == "__main__":
    import sys

    b = sys.argv[1] if len(sys.argv) > 1 else "roasting"
    print(f"raw:      {b}")
    print(f"expanded: {expand_brief(b)}")
