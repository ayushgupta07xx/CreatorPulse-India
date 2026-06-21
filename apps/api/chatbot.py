"""Grounded product-help assistant for CreatorPulse India.

A narrow product guide: it explains what CreatorPulse is, how its models work, and
what its numbers mean — and it can call a small, whitelisted set of the product's
own endpoints to answer with REAL data (a creator's stats, a match, a niche trend).
It is grounded so it cannot invent metrics, and bounded so it stays a product guide,
not open analytics over the dataset (that lane belongs to a separate product).

Uses Groq's OpenAI-compatible endpoint via `requests` (already a core dep). The
endpoint that calls it is sync, so FastAPI runs the blocking request in a threadpool.
Tool execution is injected by the caller (main.py) to avoid a circular import.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_USER_CHARS = 1500  # per message
MAX_TURNS = 12  # cap history sent upstream
MAX_TOOL_ROUNDS = 2  # cap tool round-trips per answer (cost + latency guard)
TIMEOUT_S = 30

SYSTEM_PROMPT = """You are the product guide for CreatorPulse India, a creator-economy
intelligence product for the Indian market. You help visitors understand what the
product is, how it works, and what its numbers mean. You are friendly, concise, and
above all HONEST.

ABOUT THE PRODUCT
- Two users: creators (analyze a channel's growth, engagement quality, niche demand,
  peers) and brands (find vetted creators by a campaign brief, with an engagement-risk
  screen and a sponsored-cost estimate).
- Data: about 12,500 Indian YouTube creators. Channel stats (subscribers, views,
  videos, engagement) come from the official YouTube Data API. The seed list of channels
  comes from an open Kaggle dataset (ODC-BY licensed, credited in LEGAL.md). No scraping.
- It runs free-forever on an open-source stack (PostgreSQL/pgvector, FastAPI, Next.js,
  Hugging Face Spaces, Vercel). Built by Ayush Gupta.

HOW THE MODELS WORK (and their honest status)
- Engagement-risk screen (XGBoost): flags channels with unusual engagement patterns. It
  is HEURISTICALLY labeled, NOT platform-verified fraud — a "worth a closer look" signal,
  never an accusation. Its accuracy (F1 about 0.83) was measured on a SIMULATED cohort,
  not real labeled fraud.
- Creator archetypes (K-means + DBSCAN, 8 clusters): a behavioral cohort label. On the
  real corpus the clusters are only weakly separated (silhouette about 0.20), so an
  archetype is a rough cohort tag and may not match a channel's stated niche. The cleaner
  0.48 silhouette figure is from a SIMULATED cohort only.
- Brand-creator match: embeds the brief and creator content (BGE-small) and ranks by
  cosine similarity plus re-ranking on niche fit, engagement risk, budget, and reach.
  Because the content embeddings only weakly separate broad creator text, very short
  briefs (one or two words) produce similar scores — richer, more specific briefs work
  much better.
- Sponsored-cost estimate: priced on REACH, not subscriber count — median views times a
  per-niche sponsored CPM, with a Shorts discount, a subscriber floor, and a cap of 50
  lakh rupees. It is a rough proxy for what a brand might pay for one sponsored video,
  NOT a quote.
- Niche-demand forecast (Prophet): 12-week forecasts per niche. The weekly history behind
  them is SIMULATED (there is no real longitudinal demand data yet), so treat the trends
  as illustrative.
- Earnings (OLS regression): a methodology artifact estimating AdSense-equivalent revenue
  only; it excludes brand deals, merch, and memberships. The app shows the reach-based
  sponsored cost instead.

KNOWN LIMITATIONS (state these plainly when relevant)
- Several headline metrics are validated against simulated cohorts because there is no
  live traffic yet — say so when asked.
- Niche labels come from the open seed dataset and carry its noise; some channels
  (especially brand or corporate accounts that don't fit the 20-niche taxonomy) can be
  mis-tagged. Short briefs can also be misread (e.g. "roasting" reads as cooking).
- There is one metrics snapshot per channel so far, so growth is shown as a niche-trend
  projection, not measured per-channel history.

YOUR RULES
- You can call tools to fetch REAL data: a creator's stats, creators matching a brief,
  or a niche's demand trend. When a question is about specific data, call a tool rather
  than guessing.
- Base any data answer ONLY on what the tool returns. If a tool returns no results, say
  you couldn't find it — NEVER fill in numbers from memory.
- Outside of tool results, never invent or estimate a number, metric, date, or creator
  detail. If you don't have it, say so.
- When a figure is simulated or heuristic (engagement risk, archetype, niche forecast,
  earnings), say so — do not present it as a real, validated result.
- Do not oversell. Name limitations honestly — that honesty is the point of this product.
- Do not judge a real creator's actual income or whether they commit fraud; the scores
  are heuristic estimates, not verdicts.
- Stay on CreatorPulse topics. If asked something unrelated, or for medical, legal, or
  financial advice, briefly decline and steer back.
- Keep answers short and plain — usually a few sentences."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_creators",
            "description": (
                "Look up real creators in the corpus by a keyword in their channel "
                "title (e.g. a creator's name). Returns their actual stats. Use when "
                "the user asks about a specific named creator."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Name/keyword to search the channel title for.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_creator_details",
            "description": (
                "Fetch full real stats for one creator by channel_id. Use when the "
                "user is viewing a creator profile and asks about it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string"},
                },
                "required": ["channel_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_creators",
            "description": (
                "Run the brand-creator match for a campaign brief (optional niche + "
                "budget in lakhs). Returns top matching creators with fit scores and "
                "cost estimates. Use for creator recommendations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "brief": {"type": "string"},
                    "niche": {
                        "type": "string",
                        "description": "Optional niche filter, e.g. 'Comedy'.",
                    },
                    "budget_lakh": {
                        "type": "number",
                        "description": "Optional per-integration budget in lakhs.",
                    },
                },
                "required": ["brief"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "niche_demand",
            "description": (
                "Get a niche's demand trend (forecast slope/direction). The forecast "
                "history is simulated, so frame it as illustrative."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "niche": {"type": "string"},
                },
                "required": ["niche"],
            },
        },
    },
]


class GroqError(RuntimeError):
    """Raised on any upstream/config failure; carries a short reason string."""


def prepare_messages(raw: list[dict]) -> list[dict]:
    """Validate, trim, and cap client turns. Returns [] if it doesn't end on a user."""
    out: list[dict] = []
    for m in raw[-MAX_TURNS:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()[:MAX_USER_CHARS]
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    if not out or out[-1]["role"] != "user":
        return []
    return out


def _call(api_key: str, model: str, convo: list[dict], tools: list | None) -> dict:
    payload: dict = {
        "model": model,
        "messages": convo,
        "temperature": 0.2,
        "max_tokens": 700,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        r = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise GroqError("network") from e
    if r.status_code == 429:
        raise GroqError("rate_limited")
    if r.status_code >= 400:
        raise GroqError(f"upstream_{r.status_code}")
    try:
        return r.json()["choices"][0]["message"]
    except (KeyError, IndexError, ValueError) as e:
        raise GroqError("bad_response") from e


def groq_chat(
    messages: list[dict],
    tool_executor: Callable[[str, dict], str] | None = None,
) -> str:
    """Grounded chat. If tool_executor is given, run a bounded tool-calling loop:
    the model may call whitelisted tools; results are fed back; after MAX_TOOL_ROUNDS
    the model must answer in text."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise GroqError("unconfigured")
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    convo: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]

    for round_i in range(MAX_TOOL_ROUNDS + 1):
        send_tools = TOOLS if (tool_executor and round_i < MAX_TOOL_ROUNDS) else None
        msg = _call(api_key, model, convo, send_tools)
        calls = msg.get("tool_calls")
        if not calls or not tool_executor:
            return (msg.get("content") or "").strip()
        convo.append(
            {
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": calls,
            }
        )
        for tc in calls:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            result = tool_executor(fn.get("name", ""), args)
            convo.append({"role": "tool", "tool_call_id": tc.get("id"), "content": result})

    final = _call(api_key, model, convo, None)
    return (final.get("content") or "").strip()
