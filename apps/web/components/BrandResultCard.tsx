"use client";

import { useState } from "react";
import type { MatchResult } from "@/lib/api";
import {
  formatCompact,
  formatINR,
  humanizeArchetype,
  riskLabel,
  riskLevel,
} from "@/lib/format";
import ScoreRadar from "@/components/ScoreRadar";

const RISK_CLASS: Record<string, string> = {
  low: "border-risk-low/40 text-risk-low",
  mid: "border-risk-mid/40 text-risk-mid",
  high: "border-risk-high/40 text-risk-high",
};

function initials(title: string): string {
  return title
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

export default function BrandResultCard({
  r,
  shortlisted,
  canAdd,
  onToggle,
}: {
  r: MatchResult;
  shortlisted: boolean;
  canAdd: boolean;
  onToggle: () => void;
}) {
  // yt3 CDN blocks hotlinking without no-referrer; fall back to initials on error.
  const [imgOk, setImgOk] = useState(true);
  const level = riskLevel(r.fraud_risk);
  const pct = Math.round(r.final_score * 100);
  const disabled = !shortlisted && !canAdd;

  const btnClass = shortlisted
    ? "mt-4 rounded-xl border border-teal/50 px-4 py-2 text-sm font-semibold text-teal transition-colors hover:bg-teal/10"
    : disabled
      ? "mt-4 cursor-not-allowed rounded-xl border border-white/10 px-4 py-2 text-sm font-semibold text-muted"
      : "mt-4 rounded-xl border border-white/15 px-4 py-2 text-sm font-semibold text-ink transition-colors hover:border-violet hover:text-violet";

  return (
    <div className="rounded-2xl bg-gradient-to-br from-violet/40 via-teal/15 to-white/5 p-px transition-transform duration-300 hover:-translate-y-1">
      <div className="flex h-full flex-col rounded-[15px] bg-surface/90 p-5 backdrop-blur">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            {imgOk && r.thumbnail_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={r.thumbnail_url}
                alt=""
                width={48}
                height={48}
                loading="lazy"
                referrerPolicy="no-referrer"
                onError={() => setImgOk(false)}
                className="h-12 w-12 shrink-0 rounded-full object-cover"
              />
            ) : (
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet to-teal font-mono text-sm font-bold text-bg">
                {initials(r.title)}
              </div>
            )}
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <div className="truncate font-semibold text-ink">{r.title}</div>
                {r.is_brand_channel && (
                  <span
                    className="shrink-0 rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted"
                    title="Corporate / brand-owned channel — not an individual creator"
                  >
                    Corporate
                  </span>
                )}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                <span className="rounded bg-white/5 px-2 py-0.5 text-xs text-muted">
                  {r.niche}
                </span>
                <span
                  className="rounded bg-white/5 px-2 py-0.5 text-xs text-muted"
                  title="Behavioral cluster — a cohort label, not necessarily the channel's niche"
                >
                  {humanizeArchetype(r.archetype)}
                </span>
                {r.is_short && (
                  <span
                    className="rounded bg-violet/15 px-2 py-0.5 text-xs font-medium text-violet"
                    title="Short-form channel — integration priced at the Shorts rate (~0.5× long-form)"
                  >
                    Shorts
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="font-mono text-2xl font-bold leading-none text-violet">{pct}</div>
            <div className="mt-1 text-[10px] uppercase tracking-wide text-muted">match</div>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-4">
          <ScoreRadar
            values={{
              content: r.cosine,
              niche: r.niche_overlap,
              budget: r.budget_fit,
              reach: r.reach_fit,
              safety: 1 - r.fraud_risk,
            }}
          />
          <dl className="grid flex-1 grid-cols-1 gap-y-3 text-sm">
            <div>
              <dt className="text-xs text-muted">Subscribers</dt>
              <dd className="font-mono text-ink">{formatCompact(r.subscriber_count)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Typical views</dt>
              <dd className="font-mono text-ink">
                {formatCompact(r.median_views ?? r.mean_views)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Est. sponsored cost</dt>
              <dd className="font-mono text-ink">{formatINR(r.est_cost_inr)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Engagement risk</dt>
              <dd>
                <span
                  className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${RISK_CLASS[level]}`}
                >
                  {riskLabel(level)}
                </span>
              </dd>
            </div>
          </dl>
        </div>

        <button onClick={onToggle} disabled={disabled} className={btnClass}>
          {shortlisted
            ? "In shortlist — remove"
            : disabled
              ? "Shortlist full (5)"
              : "Add to shortlist"}
        </button>
      </div>
    </div>
  );
}
