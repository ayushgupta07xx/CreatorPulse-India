"""CreatorPulse India — product API.

Serves the creator-economy intelligence product to the Next.js (Vercel) frontend:
corpus stats, creator search/profile, niche-demand forecast, and brand->creator
matching. Reads Neon/pgvector + the committed models/ via the shared
apps.ml.match logic (single-sourced with the Streamlit app; the torch/BGE match
engine lives here, where there's memory headroom).

Run locally from the repo root:
    set -a; source .env; set +a
    uvicorn apps.api.main:app --port 8000
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

import apps.ml.match as match_engine
from apps.api.cache import cache_get, cache_set
from apps.api.chatbot import GroqError, groq_chat, prepare_messages
from apps.ingest import quota_tracker
from apps.ml.pricing import integration_cost_point

REPO = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO / "models"

# Comma-separated allowed origins for the Vercel frontend; localhost for dev.
_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CREATORPULSE_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

_NUMERIC = (
    "subscriber_count",
    "mean_views",
    "view_count",
    "video_count",
    "fraud_risk",
    "est_cost_inr",
    "est_cost_low_inr",
    "est_cost_high_inr",
    "cosine",
    "niche_overlap",
    "budget_fit",
    "final_score",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm model + catalog so the first user request isn't cold.
    if os.environ.get("DATABASE_URL"):
        try:
            match_engine.get_encoder()
            _display()
        except Exception as e:
            print(f"warmup skipped: {e}")
    else:
        print("DATABASE_URL not set — warmup skipped")
    yield


app = FastAPI(title="CreatorPulse India API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _display() -> pd.DataFrame:
    """Ranking catalog (cached in match) enriched with display fields."""
    creators, _ = match_engine.get_catalog()
    eng = match_engine.get_engine()
    dim = pd.read_sql(
        text(
            "select distinct on (c.channel_id) c.channel_id, c.title, "
            "s.thumbnail_url from marts.dim_channel c "
            "left join staging.channels s on s.channel_id = c.channel_id "
            "order by c.channel_id, c.effective_from desc"
        ),
        eng,
    )
    df = creators.merge(dim, on="channel_id", how="left")
    for col in _NUMERIC:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@lru_cache(maxsize=1)
def _forecast() -> dict:
    fc = joblib.load(MODELS_DIR / "niche_forecast_v1.joblib")
    return fc if isinstance(fc, dict) else {}


def _records(df: pd.DataFrame) -> list[dict]:
    """JSON-safe records (NaN -> null, numpy/Decimal -> json)."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> dict:
    return quota_tracker.usage()


@app.get("/stats")
def stats() -> dict:
    cached = cache_get("stats")
    if cached is not None:
        return cached
    df = _display()
    out = {
        "creators": int(len(df)),
        "niches": int(df["niche"].nunique()),
        "archetypes": int(df["archetype"].nunique()),
    }
    cache_set("stats", out, ttl_seconds=300)
    return out


@app.get("/creators")
def list_creators(q: str = Query(""), limit: int = 20) -> list[dict]:
    df = _display()
    if q:
        df = df[df["title"].fillna("").str.contains(q, case=False, na=False)]
    cols = [
        c
        for c in (
            "channel_id",
            "title",
            "thumbnail_url",
            "niche",
            "archetype",
            "subscriber_count",
            "mean_views",
            "median_views",
            "video_count",
            "fraud_risk",
            "est_cost_inr",
            "est_cost_low_inr",
            "est_cost_high_inr",
        )
        if c in df.columns
    ]
    return _records(df[cols].head(max(1, min(limit, 100))))


@app.get("/creators/{channel_id}")
def get_creator(channel_id: str) -> dict:
    df = _display()
    row = df[df["channel_id"] == channel_id]
    if row.empty:
        raise HTTPException(status_code=404, detail="creator not indexed")
    r = _records(row)[0]
    reach = r.get("median_views") or r.get("mean_views") or 0
    r["est_sponsored_cost_inr"] = integration_cost_point(
        reach,
        r.get("niche"),
        r.get("subscriber_count"),
        r.get("mean_duration_seconds"),
    )
    r["niche_slope"] = _forecast().get("slopes", {}).get(r.get("niche"))
    return r


@app.get("/niches/{niche}/forecast")
def get_niche_forecast(niche: str) -> dict:
    cache_key = f"forecast:{niche}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    fc = _forecast()
    forecasts = fc.get("forecasts", {})
    if niche not in forecasts:
        raise HTTPException(status_code=404, detail="no forecast for niche")
    series = forecasts[niche]
    if isinstance(series, pd.DataFrame):
        series = _records(series)
    elif isinstance(series, pd.Series):
        series = json.loads(series.to_json(date_format="iso"))
    out = {"niche": niche, "slope": fc.get("slopes", {}).get(niche), "forecast": series}
    cache_set(cache_key, out, ttl_seconds=3600)
    return out


@app.get("/creators/{channel_id}/peers")
def get_creator_peers(channel_id: str, k: int = 10) -> dict:
    """Peers in the same niche, ranked by reach proximity (log10 mean_views);
    this creator's engagement percentile within the niche; niche medians for
    rule-based tips. niche-grouped, reach-ranked (see docs/decisions.md).
    In-memory over the ranking catalog — no extra DB round-trip."""
    df = _display()
    row = df[df["channel_id"] == channel_id]
    if row.empty:
        raise HTTPException(status_code=404, detail="creator not indexed")
    r = row.iloc[0]

    niche = r.get("niche")
    cohort = df[df["niche"] == niche] if (niche is not None and pd.notna(niche)) else df

    er = "mean_engagement_rate"
    pct = None
    if er in cohort.columns:
        vals = pd.to_numeric(cohort[er], errors="coerce").dropna()
        me = pd.to_numeric(pd.Series([r.get(er)]), errors="coerce").iloc[0]
        if pd.notna(me) and len(vals) > 1:
            pct = round(float((vals < me).mean()) * 100, 1)

    peers_df = cohort[cohort["channel_id"] != channel_id].copy()
    if "mean_views" in peers_df.columns:
        target = float(r.get("mean_views") or 0.0)
        tgt_log = np.log10(max(target, 1.0))
        mv = pd.to_numeric(peers_df["mean_views"], errors="coerce").fillna(0.0)
        peers_df["_dist"] = (np.log10(mv.clip(lower=1.0)) - tgt_log).abs()
        peers_df = peers_df.sort_values("_dist")
    peer_cols = [
        c
        for c in (
            "channel_id",
            "title",
            "thumbnail_url",
            "niche",
            "archetype",
            "subscriber_count",
            "mean_views",
            "median_views",
            "video_count",
            "fraud_risk",
            "est_cost_inr",
            "est_cost_low_inr",
            "est_cost_high_inr",
        )
        if c in peers_df.columns
    ]
    peers = _records(peers_df[peer_cols].head(max(1, min(k, 25))))

    def _median(col: str) -> float | None:
        if col not in cohort.columns:
            return None
        v = pd.to_numeric(cohort[col], errors="coerce").median()
        return None if pd.isna(v) else float(v)

    medians = {
        c: _median(c)
        for c in (
            "mean_views",
            "mean_engagement_rate",
            "videos_last_30d",
            "mean_inter_video_days",
        )
    }

    return {
        "niche": niche,
        "cohort_size": int(len(cohort)),
        "engagement_percentile": pct,
        "cohort_medians": medians,
        "peers": peers,
    }


@app.get("/niches")
def list_niches() -> list[dict]:
    """Per-niche summary: creator count, median reach, median engagement, and the
    forecast trend slope. In-memory over the ranking catalog."""
    cached = cache_get("niches")
    if cached is not None:
        return cached
    df = _display()
    if "niche" not in df.columns:
        return []
    slopes = _forecast().get("slopes", {})
    out = []
    for niche, g in df.groupby("niche"):
        if niche is None or (isinstance(niche, float) and pd.isna(niche)):
            continue
        mv = pd.to_numeric(g["mean_views"], errors="coerce").median()
        er = pd.to_numeric(g["mean_engagement_rate"], errors="coerce").median()
        out.append(
            {
                "niche": str(niche),
                "creators": int(len(g)),
                "median_views": None if pd.isna(mv) else float(mv),
                "median_engagement_rate": None if pd.isna(er) else float(er),
                "slope": slopes.get(str(niche)),
            }
        )
    out.sort(key=lambda x: x["creators"], reverse=True)
    cache_set("niches", out, ttl_seconds=300)
    return out


@app.get("/niches/{niche}/creators")
def list_niche_creators(niche: str, k: int = 24) -> list[dict]:
    """Top creators in a niche by reach (mean_views desc). In-memory."""
    df = _display()
    if "niche" not in df.columns:
        return []
    sub = df[df["niche"] == niche].copy()
    if sub.empty:
        return []
    rank_col = "median_views" if "median_views" in sub.columns else "mean_views"
    sub["_mv"] = pd.to_numeric(sub[rank_col], errors="coerce").fillna(0.0)
    # Substance floor: drop thin catalogs (e.g. single viral uploads) when it
    # still leaves creators; keeps the leaderboard useful to a brand.
    if "video_count" in sub.columns:
        vc = pd.to_numeric(sub["video_count"], errors="coerce").fillna(0)
        substantive = sub[vc >= 10]
        if not substantive.empty:
            sub = substantive
    # Active creators (uploaded in last 90d) lead; dormant back-catalogs after.
    if "videos_last_90d" in sub.columns:
        active = (pd.to_numeric(sub["videos_last_90d"], errors="coerce").fillna(0) > 0).astype(int)
        sub = sub.assign(_active=active).sort_values(["_active", "_mv"], ascending=[False, False])
    else:
        sub = sub.sort_values("_mv", ascending=False)
    cols = [
        c
        for c in (
            "channel_id",
            "title",
            "thumbnail_url",
            "niche",
            "archetype",
            "subscriber_count",
            "mean_views",
            "median_views",
            "video_count",
            "fraud_risk",
            "est_cost_inr",
            "est_cost_low_inr",
            "est_cost_high_inr",
        )
        if c in sub.columns
    ]
    return _records(sub[cols].head(max(1, min(k, 60))))


class MatchRequest(BaseModel):
    brief: str
    budget_lakh: float = 15.0
    top_k: int = 20
    rerank: bool = True
    niche_filter: str | None = None
    min_views: float = match_engine.MIN_VIEWS_DEFAULT


@app.post("/match")
def post_match(req: MatchRequest) -> list[dict]:
    out = match_engine.match(
        req.brief,
        budget_lakh=req.budget_lakh,
        top_k=req.top_k,
        rerank=req.rerank,
        niche_filter=req.niche_filter,
        min_views=req.min_views,
    )
    disp_cols = [
        c
        for c in ("channel_id", "title", "thumbnail_url", "subscriber_count", "mean_views")
        if c in _display().columns
    ]
    out = out.merge(_display()[disp_cols], on="channel_id", how="left")
    return _records(out)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    context: dict | None = None


def _creator_brief(r: dict) -> dict:
    return {
        "channel_id": r.get("channel_id"),
        "title": r.get("title"),
        "niche": r.get("niche"),
        "subscribers": r.get("subscriber_count"),
        "median_views": r.get("median_views"),
        "mean_views": r.get("mean_views"),
        "engagement_risk_score": r.get("fraud_risk"),
        "est_sponsor_cost_inr": [r.get("est_cost_low_inr"), r.get("est_cost_high_inr")],
    }


def _creator_full(r: dict) -> dict:
    return {
        "channel_id": r.get("channel_id"),
        "title": r.get("title"),
        "niche": r.get("niche"),
        "archetype": r.get("archetype"),
        "subscribers": r.get("subscriber_count"),
        "total_views": r.get("view_count"),
        "videos": r.get("video_count"),
        "median_views": r.get("median_views"),
        "mean_views": r.get("mean_views"),
        "engagement_risk_score": r.get("fraud_risk"),
        "est_sponsor_cost_inr": r.get("est_sponsored_cost_inr"),
        "niche_slope": r.get("niche_slope"),
    }


def _match_brief(r: dict) -> dict:
    score = r.get("final_score")
    if score is None:
        score = r.get("score")
    return {
        "channel_id": r.get("channel_id"),
        "title": r.get("title"),
        "niche": r.get("niche"),
        "match_score": round(float(score) * 100) if score is not None else None,
        "subscribers": r.get("subscriber_count"),
        "mean_views": r.get("mean_views"),
    }


def _chat_tool_executor(name: str, args: dict) -> str:
    """Dispatch a whitelisted chatbot tool to the real handlers, returning compact JSON.
    Never fabricates: empty or not-found results come back as such so the model says so."""
    try:
        if name == "search_creators":
            q = str(args.get("query", "")).strip()
            if not q:
                return json.dumps({"results": []})
            rows = list_creators(q=q, limit=5)
            return json.dumps({"results": [_creator_brief(r) for r in rows]})
        if name == "get_creator_details":
            cid = str(args.get("channel_id", "")).strip()
            return json.dumps(_creator_full(get_creator(cid)))
        if name == "find_creators":
            brief = str(args.get("brief", "")).strip()
            if not brief:
                return json.dumps({"results": []})
            niche = args.get("niche") or None
            if niche:
                opts = _display()["niche"].dropna().unique().tolist()
                niche = next((o for o in opts if o.lower() == str(niche).lower()), niche)
            req = MatchRequest(
                brief=brief,
                niche_filter=niche,
                budget_lakh=float(args.get("budget_lakh") or 15),
            )
            rows = post_match(req)[:5]
            return json.dumps({"results": [_match_brief(r) for r in rows]})
        if name == "niche_demand":
            niche = str(args.get("niche", "")).strip()
            available = list(_forecast().get("forecasts", {}).keys())
            resolved = next((k for k in available if k.lower() == niche.lower()), None)
            if resolved is None:
                return json.dumps(
                    {"error": f"no forecast for '{niche}'", "available_niches": available}
                )
            fc = get_niche_forecast(resolved)
            slope = fc.get("slope") or 0
            direction = "growing" if slope > 0 else "declining" if slope < 0 else "flat"
            return json.dumps(
                {
                    "niche": fc.get("niche", resolved),
                    "slope": fc.get("slope"),
                    "direction": direction,
                    "note": "forecast history is simulated",
                }
            )
        return json.dumps({"error": f"unknown tool: {name}"})
    except HTTPException as e:
        return json.dumps({"error": str(e.detail)})
    except (ValueError, KeyError, TypeError) as e:
        return json.dumps({"error": f"tool failed: {e}"})


def _with_context(msgs: list[dict], context: dict | None) -> list[dict]:
    """Prepend a short note to the last user turn naming the page the user is on, so
    the model can pick the right tool (e.g. fetch the creator they're looking at)."""
    if not context or not msgs:
        return msgs
    cid = context.get("channel_id")
    page = context.get("page")
    if cid:
        note = f"[The user is currently viewing the creator profile channel_id={cid}.] "
    elif page:
        note = f"[The user is currently on the {page} page.] "
    else:
        return msgs
    last = msgs[-1]
    return [*msgs[:-1], {**last, "content": note + last["content"]}]


@app.post("/chat")
def post_chat(req: ChatRequest) -> dict:
    msgs = prepare_messages([m.model_dump() for m in req.messages])
    if not msgs:
        raise HTTPException(status_code=400, detail="Send a question to the assistant.")
    msgs = _with_context(msgs, req.context)
    try:
        reply = groq_chat(msgs, tool_executor=_chat_tool_executor)
    except GroqError as e:
        reason = str(e)
        if reason == "unconfigured":
            raise HTTPException(
                status_code=503,
                detail="The assistant isn't configured yet.",
            ) from e
        if reason == "rate_limited":
            raise HTTPException(
                status_code=429,
                detail="The assistant is busy right now — try again in a moment.",
            ) from e
        raise HTTPException(
            status_code=502,
            detail="The assistant is temporarily unavailable.",
        ) from e
    return {"reply": reply}
