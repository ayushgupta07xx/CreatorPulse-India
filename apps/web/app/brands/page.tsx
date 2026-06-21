"use client";

import { useMemo, useState } from "react";
import { matchCreators, type MatchResult } from "@/lib/api";
import {
  formatCompact,
  formatINR,
  humanizeArchetype,
  riskLabel,
  riskLevel,
} from "@/lib/format";
import BrandResultCard from "@/components/BrandResultCard";
import Reveal from "@/components/Reveal";

const NICHES = [
  "Tech", "Gaming", "Beauty", "Food", "Fitness", "Comedy", "Education",
  "Lifestyle", "Music", "Devotional", "News", "Vlogs", "Auto", "DIY",
  "Travel", "Sports", "Finance", "Parenting", "Fashion", "Reactions",
];

const SAMPLE =
  "Vegan skincare D2C launching nationwide, primary audience women 22–35 metro tier-1, looking for authentic everyday-routine creators.";

const MAX_SHORTLIST = 5;

type Sort = "match" | "cost" | "reach" | "risk";

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "done"; results: MatchResult[]; explainer: string | null }
  | { kind: "error"; message: string };

const RISK_CLASS: Record<string, string> = {
  low: "border-risk-low/40 text-risk-low",
  mid: "border-risk-mid/40 text-risk-mid",
  high: "border-risk-high/40 text-risk-high",
};

function CompareRow({ label, cells }: { label: string; cells: string[] }) {
  return (
    <tr className="border-t border-white/5">
      <td className="p-3 font-sans text-muted">{label}</td>
      {cells.map((c, i) => (
        <td key={i} className="p-3">
          {c}
        </td>
      ))}
    </tr>
  );
}

export default function BrandsPage() {
  const [brief, setBrief] = useState("");
  const [niche, setNiche] = useState("");
  const [budget, setBudget] = useState(15);
  const [state, setState] = useState<State>({ kind: "idle" });
  const [sort, setSort] = useState<Sort>("match");
  const [hideHighRisk, setHideHighRisk] = useState(false);
  const [shortlist, setShortlist] = useState<MatchResult[]>([]);

  async function run() {
    const text = brief.trim();
    if (!text) return;
    setState({ kind: "loading" });
    try {
      const res = await matchCreators({
        brief: text,
        budget_lakh: budget,
        niche_filter: niche || null,
        top_k: 20,
        rerank: true,
      });
      setState({ kind: "done", results: res.results, explainer: res.explainer });
    } catch (e) {
      setState({
        kind: "error",
        message: e instanceof Error ? e.message : "Match failed",
      });
    }
  }

  function toggleShortlist(r: MatchResult) {
    setShortlist((cur) => {
      const exists = cur.some((x) => x.channel_id === r.channel_id);
      if (exists) return cur.filter((x) => x.channel_id !== r.channel_id);
      if (cur.length >= MAX_SHORTLIST) return cur;
      return [...cur, r];
    });
  }

  const visible = useMemo(() => {
    if (state.kind !== "done") return [];
    let rows = state.results;
    if (hideHighRisk) rows = rows.filter((r) => riskLevel(r.fraud_risk) !== "high");
    const sorted = [...rows];
    sorted.sort((a, b) => {
      if (sort === "match") return b.final_score - a.final_score;
      if (sort === "cost") return a.est_cost_inr - b.est_cost_inr;
      if (sort === "reach") return b.mean_views - a.mean_views;
      return a.fraud_risk - b.fraud_risk;
    });
    return sorted;
  }, [state, sort, hideHighRisk]);

  const shortlistIds = new Set(shortlist.map((s) => s.channel_id));

  return (
    <div className="mx-auto max-w-wrap px-6 py-12">
      <Reveal>
        <h1 className="font-display text-3xl font-bold tracking-tight text-ink sm:text-4xl">
          Brief a campaign
        </h1>
        <p className="mt-3 max-w-xl text-muted">
          Describe the campaign and budget. We match creators on content fit,
          niche overlap, reach, and budget, then screen each one for engagement
          risk before it reaches your shortlist.
        </p>
      </Reveal>

      <Reveal delay={0.06}>
        <div className="mt-8 rounded-2xl border border-white/10 bg-surface/60 p-5">
          <label htmlFor="brief" className="text-xs text-muted">
            Campaign brief
          </label>
          <textarea
            id="brief"
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            rows={3}
            placeholder="e.g. Vegan skincare D2C launching nationwide, women 22–35, authentic everyday-routine creators"
            className="mt-1.5 w-full resize-y rounded-xl border border-white/10 bg-bg/60 px-4 py-3 text-ink placeholder:text-muted focus:border-violet focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet"
          />
          <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="sm:w-56">
              <label htmlFor="niche" className="text-xs text-muted">
                Niche
              </label>
              <select
                id="niche"
                value={niche}
                onChange={(e) => setNiche(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-white/10 bg-bg/60 px-3 py-2.5 text-ink focus:border-violet focus:outline-none"
              >
                <option value="">Any niche</option>
                {NICHES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label
                htmlFor="budget"
                className="flex items-center justify-between text-xs text-muted"
              >
                <span>Budget per integration</span>
                <span className="font-mono text-ink">{formatINR(budget * 100000)}</span>
              </label>
              <input
                id="budget"
                type="range"
                min={1}
                max={50}
                step={1}
                value={budget}
                onChange={(e) => setBudget(Number(e.target.value))}
                className="mt-3 w-full accent-violet"
              />
            </div>
            <button
              onClick={run}
              className="btn-sheen shrink-0 rounded-xl bg-ink px-6 py-3 text-sm font-semibold text-bg transition-transform hover:-translate-y-0.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet"
            >
              Find creators
            </button>
          </div>
          <button
            onClick={() => {
              setBrief(SAMPLE);
              setNiche("Beauty");
              setBudget(15);
            }}
            className="mt-3 text-xs text-muted underline-offset-2 transition-colors hover:text-ink hover:underline"
          >
            Try a sample brief
          </button>
        </div>
      </Reveal>

      <div className="mt-10">
        {state.kind === "loading" && <p className="text-muted">Matching creators…</p>}

        {state.kind === "error" && (
          <p className="text-risk-high">
            Couldn&apos;t reach the match service ({state.message}). The API may be
            waking up — try again in a few seconds.
          </p>
        )}

        {state.kind === "done" && state.results.length === 0 && (
          <p className="text-muted">
            {state.explainer ?? (
              <>
                No creators cleared the budget and reach floor for this brief. Try
                a broader niche or a higher budget.
              </>
            )}
          </p>
        )}

        {state.kind === "done" && state.results.length > 0 && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="text-sm text-muted">
                {visible.length} of {state.results.length} matches
              </p>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-sm text-muted">
                  <input
                    type="checkbox"
                    checked={hideHighRisk}
                    onChange={(e) => setHideHighRisk(e.target.checked)}
                    className="accent-violet"
                  />
                  Hide high-risk
                </label>
                <label className="flex items-center gap-2 text-sm text-muted">
                  Sort
                  <select
                    value={sort}
                    onChange={(e) => setSort(e.target.value as Sort)}
                    className="rounded-lg border border-white/10 bg-surface/60 px-2 py-1.5 text-ink focus:border-violet focus:outline-none"
                  >
                    <option value="match">Match score</option>
                    <option value="cost">Lowest cost</option>
                    <option value="reach">Most reach</option>
                    <option value="risk">Lowest risk</option>
                  </select>
                </label>
              </div>
            </div>

            <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
              {visible.map((r, i) => (
                <Reveal key={r.channel_id} delay={Math.min(i * 0.04, 0.4)}>
                  <BrandResultCard
                    r={r}
                    shortlisted={shortlistIds.has(r.channel_id)}
                    canAdd={shortlist.length < MAX_SHORTLIST}
                    onToggle={() => toggleShortlist(r)}
                  />
                </Reveal>
              ))}
            </div>
          </>
        )}
      </div>

      {shortlist.length > 0 && (
        <div className="mt-12">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-xl font-bold text-ink">
              Shortlist ({shortlist.length}/{MAX_SHORTLIST})
            </h2>
            <button
              onClick={() => setShortlist([])}
              className="text-sm text-muted transition-colors hover:text-ink"
            >
              Clear
            </button>
          </div>

          {shortlist.length >= 2 ? (
            <div className="mt-4 overflow-x-auto rounded-2xl border border-white/10">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-left text-muted">
                    <th className="p-3 font-medium">Creator</th>
                    {shortlist.map((s) => (
                      <th key={s.channel_id} className="p-3 font-semibold text-ink">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate">{s.title}</span>
                          <button
                            onClick={() => toggleShortlist(s)}
                            aria-label={`Remove ${s.title}`}
                            className="text-muted transition-colors hover:text-risk-high"
                          >
                            ×
                          </button>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="font-mono text-ink">
                  <CompareRow
                    label="Match"
                    cells={shortlist.map((s) => String(Math.round(s.final_score * 100)))}
                  />
                  <CompareRow
                    label="Subscribers"
                    cells={shortlist.map((s) => formatCompact(s.subscriber_count))}
                  />
                  <CompareRow
                    label="Avg. views"
                    cells={shortlist.map((s) => formatCompact(s.mean_views))}
                  />
                  <CompareRow
                    label="Est. cost"
                    cells={shortlist.map((s) => formatINR(s.est_cost_inr))}
                  />
                  <CompareRow label="Niche" cells={shortlist.map((s) => s.niche)} />
                  <CompareRow
                    label="Archetype"
                    cells={shortlist.map((s) => humanizeArchetype(s.archetype))}
                  />
                  <tr className="border-t border-white/5">
                    <td className="p-3 font-sans text-muted">Engagement risk</td>
                    {shortlist.map((s) => {
                      const lv = riskLevel(s.fraud_risk);
                      return (
                        <td key={s.channel_id} className="p-3">
                          <span
                            className={`inline-flex items-center rounded-full border px-2 py-0.5 font-sans text-xs font-semibold ${RISK_CLASS[lv]}`}
                          >
                            {riskLabel(lv)}
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted">
              Add one more creator to compare side by side.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
