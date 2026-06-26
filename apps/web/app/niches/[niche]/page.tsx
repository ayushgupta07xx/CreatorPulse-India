"use client";

import { useEffect, useState } from "react";
import EmptyState, { AlertIcon, InboxIcon } from "@/components/EmptyState";
import SkeletonGrid from "@/components/SkeletonGrid";
import Link from "next/link";
import {
  getNiches,
  getNicheForecast,
  getNicheCreators,
  type NicheSummary,
  type NicheForecast,
  type CreatorSummary,
} from "@/lib/api";
import { formatCompact } from "@/lib/format";
import Reveal from "@/components/Reveal";
import ForecastChart from "@/components/ForecastChart";
import CreatorCard from "@/components/CreatorCard";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-surface px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 font-mono text-lg text-ink">{value}</div>
    </div>
  );
}

export default function NicheDetail({ params }: { params: { niche: string } }) {
  const niche = decodeURIComponent(params.niche);
  const [summary, setSummary] = useState<NicheSummary | null>(null);
  const [forecast, setForecast] = useState<NicheForecast | null>(null);
  const [creators, setCreators] = useState<CreatorSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([
      getNiches()
        .then((ns) => ns.find((n) => n.niche === niche) ?? null)
        .catch(() => null),
      getNicheForecast(niche).catch(() => null),
      getNicheCreators(niche, 24).catch(() => null),
    ]).then(([s, f, c]) => {
      if (!alive) return;
      setSummary(s);
      setForecast(f);
      setCreators(c);
      if (!s && !f && !c) setFailed(true);
    });
    return () => {
      alive = false;
    };
  }, [niche]);

  const up = (summary?.slope ?? 0) > 0;
  const down = (summary?.slope ?? 0) < 0;
  const dir = up ? "Rising" : down ? "Cooling" : "Flat";
  const dirClass = up
    ? "border-teal/30 text-teal"
    : down
      ? "border-pink/30 text-pink"
      : "border-white/15 text-muted";

  return (
    <div className="mx-auto max-w-wrap px-6 py-12">
      <Reveal>
        <Link
          href="/niches"
          className="font-mono text-xs text-muted transition-colors hover:text-ink"
        >
          ← All niches
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <h1 className="font-display text-3xl font-bold tracking-tight text-ink sm:text-4xl">
            {niche}
          </h1>
          {summary && (
            <span
              className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${dirClass}`}
            >
              {dir}
            </span>
          )}
        </div>
      </Reveal>

      {failed && (
        <EmptyState
          tone="error"
          icon={<AlertIcon />}
          title="Couldn't load this niche"
          body="The API may be waking up — try again shortly."
        />
      )}

      {summary && (
        <Reveal delay={0.05}>
          <dl className="mt-6 grid grid-cols-3 gap-3">
            <Stat label="Creators" value={formatCompact(summary.creators)} />
            <Stat
              label="Median views"
              value={summary.median_views == null ? "—" : formatCompact(summary.median_views)}
            />
            <Stat
              label="Median ER"
              value={
                summary.median_engagement_rate == null
                  ? "—"
                  : `${(summary.median_engagement_rate * 100).toFixed(1)}%`
              }
            />
          </dl>
        </Reveal>
      )}

      {forecast && forecast.forecast.length >= 2 && (
        <Reveal delay={0.1}>
          <section className="mt-12">
            <h2 className="font-display text-xl font-bold text-ink">Niche demand forecast</h2>
            <p className="mt-1 text-sm text-muted">
              Weekly aggregate views, 12-week horizon with an 80% interval. The demand series
              is simulated — labeled, not measured.
            </p>
            <div className="mt-4 rounded-2xl border border-white/10 bg-surface p-4">
              <ForecastChart forecast={forecast.forecast} horizon={12} />
            </div>
          </section>
        </Reveal>
      )}

      <section className="mt-12">
        <Reveal>
          <h2 className="font-display text-xl font-bold text-ink">Top creators in {niche}</h2>
          <p className="mt-1 text-sm text-muted">
            Ranked by typical reach (median views); active creators first.
          </p>
        </Reveal>
        {!creators && !failed && <SkeletonGrid variant="creator" count={6} />}
        {creators && creators.length === 0 && (
          <EmptyState icon={<InboxIcon />} title="No creators here yet" body="No creators are indexed in this niche." />
        )}
        {creators && creators.length > 0 && (
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {creators.map((c, i) => (
              <Reveal key={c.channel_id} delay={Math.min(i * 0.03, 0.3)}>
                <Link href={`/creators/${c.channel_id}`} className="block h-full">
                  <CreatorCard c={c} />
                </Link>
              </Reveal>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
