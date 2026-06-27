"""Faithfulness eval for the CreatorPulse grounded assistant.

Runs each golden case (evaluation/faithfulness_cases.yaml) through the REAL
groq_chat() tool-calling loop, capturing the tool calls/results that grounded
the answer. An LLM judge (GROQ_JUDGE_MODEL, default openai/gpt-oss-20b) then
scores each reply for faithfulness to that tool output: does every number/claim
trace to a tool result or the assistant's allowed framing, with nothing invented?

Non-invasive: wraps the real _chat_tool_executor to tee (name, args, result) per
case — no change to apps/api or apps/ml.

Resumable: appends each scored case to evaluation/faithfulness_results.jsonl;
re-running skips already-scored case ids, so a Groq free-tier 429 mid-run never
loses progress. Delete the .jsonl (or pass --fresh) to start over.

Run:  python evaluation/faithfulness_eval.py            (needs GROQ_API_KEY)
      python evaluation/faithfulness_eval.py --fresh    (ignore prior results)
Exit: 1 if mean faithfulness < THRESHOLD or any case errored (so it CAN be
      CI-wired later; it is NOT in the merge gate today).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import yaml

# Real product code — the thing under test.
from apps.api.chatbot import DEFAULT_MODEL, GroqError, _call, groq_chat
from apps.api.main import _chat_tool_executor

HERE = Path(__file__).resolve().parent
CASES = HERE / "faithfulness_cases.yaml"
RESULTS = HERE / "faithfulness_results.jsonl"
THRESHOLD = 0.80  # mean faithfulness below this fails the run
JUDGE_MODEL_ENV = "GROQ_JUDGE_MODEL"
JUDGE_MODEL_DEFAULT = "openai/gpt-oss-20b"

JUDGE_SYSTEM = (
    "You are a strict evaluator of an AI product assistant's FAITHFULNESS to its "
    "retrieved data. You are given a user question, the exact TOOL OUTPUT the "
    "assistant received (JSON; this is the only ground-truth data it had), and the "
    "assistant's REPLY. Judge ONLY faithfulness, not style or helpfulness.\n\n"
    "FAITHFUL means: every concrete number, name, and factual claim in the reply "
    "traces to the tool output, OR is a correct general statement about how the "
    "product works, OR is an honest refusal / 'I don't have that' / 'not knowable "
    "from public data'. UNFAITHFUL means: the reply invents a number, creator, "
    "income figure, or stat NOT present in the tool output, or asserts a specific "
    "fraud verdict or Instagram data the product does not have.\n\n"
    "Note: refusing to give an exact creator income, refusing to name definite "
    "fraudsters, declining Instagram data, and saying a made-up channel was not "
    "found are all FAITHFUL (score high). Inventing such figures is UNFAITHFUL.\n\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences:\n"
    '{"score": <float 0.0-1.0>, "verdict": "faithful"|"unfaithful"|"partial", '
    '"rationale": "<one sentence citing the specific claim you judged>"}'
)

# Documented product mechanics — ground truth for kind=="product" questions, where
# the assistant explains behaviour and calls no tool (so tool output is empty).
# These mirror the Canonical Numbers / ADRs; an explanation matching them is FAITHFUL.
PRODUCT_FACTS = (
    "DOCUMENTED PRODUCT MECHANICS (treat as ground truth for explanation answers):\n"
    "- Brand-creator match: embeds brief + creator content (BGE-small), cosine similarity "
    "for candidates, then re-ranks on niche overlap, engagement-risk penalty, budget fit, "
    "and reach. Short/polysemous briefs are expanded first (Stage-0, Groq).\n"
    "- Engagement risk: an XGBoost classifier trained on HEURISTIC labels over public "
    "signals — risk-screening, NOT platform-verified fraud. Never names definite fraudsters.\n"
    "- Sponsored-video cost: reach-first — median views x per-niche sponsored CPM / 1000, "
    "x format factor (Shorts x0.1), floored by subscriber base, capped at Rs 50 lakh. "
    "A rough proxy, not a quote. (NOT subscriber-count based.)\n"
    "- Archetype clusters: K-means k=8 + DBSCAN; real composite silhouette ~0.20 (modest); "
    "clusters are behavioural and don't cleanly separate broad creator text. Honest about this.\n"
    "- Data source: channel stats come from the official YouTube Data API v3; the channel "
    "seed list comes from an open Kaggle dataset (ODC-BY, credited in LEGAL.md). No scraping. "
    "Instagram is out of scope (v2). "
    "Corpus: ~12,500 (exactly 12,547) Indian YouTube creators across 20 niches, "
    "one metrics snapshot. Creator counts/niches read live from the product DB.\n"
)


def _load_cases() -> list[dict]:
    return yaml.safe_load(CASES.read_text(encoding="utf-8"))


def _done_ids() -> set[str]:
    if not RESULTS.exists():
        return set()
    ids = set()
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                ids.add(json.loads(line)["id"])
            except (ValueError, KeyError):
                pass
    return ids


def _run_case(question: str) -> tuple[str, list[dict]]:
    """Run the real grounded chat; tee every tool call+result for the judge."""
    transcript: list[dict] = []

    def teeing_executor(name: str, args: dict) -> str:
        result = _chat_tool_executor(name, args)
        transcript.append({"tool": name, "args": args, "result": result})
        return result

    reply = groq_chat([{"role": "user", "content": question}], tool_executor=teeing_executor)
    return reply, transcript


def _judge(
    api_key: str, model: str, kind: str, question: str, transcript: list[dict], reply: str
) -> dict:
    tool_output = json.dumps(transcript, ensure_ascii=False) if transcript else "(no tools called)"
    if kind == "product":
        tool_output = (
            f"{PRODUCT_FACTS}\n(Tool calls, if any: "
            f"{json.dumps(transcript, ensure_ascii=False) if transcript else 'none'})"
        )
    user = (
        f"QUESTION:\n{question}\n\n"
        f"TOOL OUTPUT (ground truth):\n{tool_output}\n\n"
        f"ASSISTANT REPLY:\n{reply}\n\n"
        "Score the reply's faithfulness now as the JSON object."
    )
    raw = _call(
        api_key,
        model,
        [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user},
        ],
        None,
        response_format={"type": "json_object"},
        temperature=0,
    )
    text = (raw.get("content") or "").strip()
    # 8b judges occasionally wrap JSON in fences or stray text — extract the object.
    if "{" in text and "}" in text:
        text = text[text.index("{") : text.rindex("}") + 1]
    try:
        obj = json.loads(text)
        score = float(obj.get("score", 0.0))
        return {
            "score": max(0.0, min(1.0, score)),
            "verdict": str(obj.get("verdict", "unknown")),
            "rationale": str(obj.get("rationale", "")),
        }
    except (ValueError, TypeError):
        return {"score": 0.0, "verdict": "judge_parse_error", "rationale": text[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="ignore prior results, score every case")
    args = ap.parse_args()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY not set — this eval calls the live Groq API.")
        return 1
    judge_model = os.environ.get(JUDGE_MODEL_ENV, JUDGE_MODEL_DEFAULT)
    answer_model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    print(f"answer model: {answer_model}  |  judge model: {judge_model}")

    if args.fresh and RESULTS.exists():
        RESULTS.unlink()
    cases = _load_cases()
    done = _done_ids()
    pending = [c for c in cases if c["id"] not in done]
    print(f"{len(cases)} cases, {len(done)} already scored, {len(pending)} to run.")

    errored = False
    with RESULTS.open("a", encoding="utf-8") as out:
        for c in pending:
            cid, kind, q = c["id"], c["kind"], c["question"]
            try:
                reply, transcript = _run_case(q)
                judged = _judge(api_key, judge_model, kind, q, transcript, reply)
            except GroqError as e:
                # 429/network — stop cleanly; progress so far is saved, re-run resumes.
                if str(e) == "rate_limited":
                    print(f"  ! {cid}: rate-limited — stopping; re-run to resume.")
                    errored = True
                    break
                print(f"  ! {cid}: GroqError({e}) — recording as failure.")
                judged = {"score": 0.0, "verdict": f"error_{e}", "rationale": ""}
                reply, transcript = "", []
            row = {
                "id": cid,
                "kind": kind,
                "question": q,
                "n_tool_calls": len(transcript),
                "reply": reply,
                **judged,
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  {cid:24s} [{kind:8s}] score={judged['score']:.2f} {judged['verdict']}")
            time.sleep(20)  # free-tier is 6k TPM on the 8b judge; space cases out

    # Aggregate over all committed results (resumed + this run).
    rows = [
        json.loads(line)
        for line in RESULTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        print("No results.")
        return 1
    mean = sum(r["score"] for r in rows) / len(rows)
    fails = [r for r in rows if r["score"] < 0.5]
    print(f"\nmean faithfulness = {mean:.3f} over {len(rows)} cases (threshold {THRESHOLD})")
    if fails:
        print("low-scoring cases (auditable — read the rationale):")
        for r in fails:
            print(f"  - {r['id']} ({r['verdict']}): {r['rationale']}")

    if errored:
        print("Run incomplete (rate-limited) — re-run to finish before trusting the mean.")
        return 1
    if mean < THRESHOLD:
        print(f"FAIL: mean faithfulness {mean:.3f} < {THRESHOLD}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
