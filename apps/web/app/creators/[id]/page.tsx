"use client";

import { useEffect, useState } from "react";
import EmptyState, { AlertIcon } from "@/components/EmptyState";
import CreatorDetailSkeleton from "@/components/CreatorDetailSkeleton";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  getCreator,
  getCreatorPeers,
  getNicheForecast,
  type CreatorDetail,
  type PeersResponse,
  type NicheForecast,
} from "@/lib/api";
import {
  formatCompact,
  formatINR,
  humanizeArchetype,
  riskLabel,
  riskLevel,
} from "@/lib/format";
import CreatorCard from "@/components/CreatorCard";
import Reveal from "@/components/Reveal";
import ForecastChart from "@/components/ForecastChart";
import ProjectionChart from "@/components/ProjectionChart";

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

function num(n: number | null | undefined): string {
  return n == null || !isFinite(n) ? "—" : new Intl.NumberFormat("en-IN").format(Math.round(n));
}

function compact(n: number | null | undefined): string {
  return n == null || !isFinite(n) ? "—" : formatCompact(n);
}

function pctStr(x: number | null | undefined): string {
  return x == null || !isFinite(x) ? "—" : `${(x * 100).toFixed(2)}%`;
}

function duration(sec: number | null | undefined): string {
  if (sec == null || !isFinite(sec)) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-surface/60 p-6">
      <h2 className="font-display text-lg font-bold tracking-tight text-ink">{title}</h2>
      <div className="mt-4">{children}</div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 font-mono text-lg text-ink">{value}</dd>
    </div>
  );
}

type Status = "loading" | "done" | "error";

export default function CreatorProfile({ params }: { params: { id: string } }) {
  const id = params.id;
  const router = useRouter();
  const [status, setStatus] = useState<Status>("loading");
  const [err, setErr] = useState("");
  const [c, setC] = useState<CreatorDetail | null>(null);
  const [peers, setPeers] = useState<PeersResponse | null>(null);
  const [forecast, setForecast] = useState<NicheForecast | null>(null);

  useEffect(() => {
    let alive = true;
    setStatus("loading");
    setPeers(null);
    setForecast(null);
    (async () => {
      try {
        const creator = await getCreator(id);
        if (!alive) return;
        setC(creator);
        setStatus("done");
        getCreatorPeers(id, 9)
          .then((p) => alive && setPeers(p))
          .catch(() => {});
        if (creator.niche) {
          getNicheForecast(creator.niche)
            .then((f) => alive && setForecast(f))
            .catch(() => {});
        }
      } catch (e) {
        if (!alive) return;
        setErr(e instanceof Error ? e.message : "Failed to load");
        setStatus("error");
      }
    })();
    return () => {
      alive = false;
    };
  }, [id]);

  if (status === "loading") {
    return <CreatorDetailSkeleton />;
  }

  if (status === "error" || !c) {
    return (
      <div className="mx-auto max-w-wrap px-6 py-12">
        <button
          onClick={() => router.back()}
          aria-label="Back"
          className="mt-2 inline-block text-lg text-muted transition-colors hover:text-ink"
        >
          ←
        </button>
        <EmptyState
          tone="error"
          icon={<AlertIcon />}
          title="Couldn't load this creator"
          body={err || "This channel isn't in the index."}
        />
      </div>
    );
  }

  const level = riskLevel(c.fraud_risk);
  const slope = forecast?.slope ?? c.niche_slope;
  const direction = slope == null ? null : slope > 0 ? "accelerating" : "declining";

  const tips: string[] = [];
  if (peers) {
    const m = peers.cohort_medians;
    const nm = peers.niche ?? c.niche;
    if (
      c.videos_last_30d != null &&
      m.videos_last_30d != null &&
      c.videos_last_30d < m.videos_last_30d
    ) {
      tips.push(
        `Posted ${num(c.videos_last_30d)} video(s) in the last 30 days vs a ${num(m.videos_last_30d)} median in ${nm} — more frequent uploads tend to track with reach here.`,
      );
    }
    if (
      c.mean_engagement_rate != null &&
      m.mean_engagement_rate != null &&
      c.mean_engagement_rate < m.mean_engagement_rate
    ) {
      tips.push(
        `Engagement rate (${pctStr(c.mean_engagement_rate)}) is below the ${nm} median (${pctStr(m.mean_engagement_rate)}) — stronger hooks and calls-to-comment are the usual levers.`,
      );
    }
    if (
      c.mean_inter_video_days != null &&
      m.mean_inter_video_days != null &&
      c.mean_inter_video_days > m.mean_inter_video_days
    ) {
      tips.push(
        `Average gap between uploads (${c.mean_inter_video_days.toFixed(1)}d) is longer than the ${nm} median (${m.mean_inter_video_days.toFixed(1)}d) — a steadier cadence helps retention.`,
      );
    }
  }

  return (
    <div className="mx-auto max-w-wrap px-6 py-12">
      <button
        onClick={() => router.back()}
        aria-label="Back"
        className="mt-2 inline-block text-lg text-muted transition-colors hover:text-ink"
      >
        ←
      </button>

      {/* header */}
      <Reveal>
        <div className="mt-6 flex flex-col gap-5 sm:flex-row sm:items-center">
          {c.thumbnail_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={c.thumbnail_url}
              alt=""
              width={96}
              height={96}
              referrerPolicy="no-referrer"
              className="h-24 w-24 shrink-0 rounded-full object-cover"
            />
          ) : (
            <div className="flex h-24 w-24 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet to-teal font-mono text-2xl font-bold text-bg">
              {initials(c.title)}
            </div>
          )}
          <div className="min-w-0">
            <h1 className="font-display text-3xl font-bold tracking-tight text-ink">{c.title}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="rounded bg-white/5 px-2 py-0.5 text-sm text-muted">{c.niche}</span>
              <span
                className="rounded bg-white/5 px-2 py-0.5 text-sm text-muted"
                title="Behavioral cluster — a cohort label, not necessarily the channel's niche"
              >
                {humanizeArchetype(c.archetype)}
              </span>
              {c.country && (
                <span className="rounded bg-white/5 px-2 py-0.5 text-sm text-muted">{c.country}</span>
              )}
            </div>
          </div>
        </div>
      </Reveal>

      <div className="mt-8 grid grid-cols-1 gap-6">
        <Reveal delay={0.04}>
          <Section title="At a glance">
            <dl className="grid grid-cols-2 gap-6 sm:grid-cols-4">
              <Stat label="Subscribers" value={formatCompact(c.subscriber_count)} />
              <Stat label="Total views" value={formatCompact(c.view_count)} />
              <Stat label="Videos" value={num(c.video_count)} />
              <Stat label="Avg views / video" value={formatCompact(c.mean_views)} />
            </dl>
            <div className="mt-6 flex flex-wrap items-end gap-x-10 gap-y-4">
              <Stat
                label="Est. sponsor cost"
                value={`${formatINR(c.est_cost_low_inr)}–${formatINR(c.est_cost_high_inr)}`}
              />
              <div>
                <dt className="text-xs text-muted">Engagement risk</dt>
                <dd className="mt-1">
                  <span
                    className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-sm font-semibold ${RISK_CLASS[level]}`}
                  >
                    {riskLabel(level)}
                  </span>
                </dd>
              </div>
            </div>
            <p className="mt-4 text-xs text-muted">
              Sponsor cost is a rough estimate of what a brand might pay to sponsor one video,
              based on the creator&apos;s audience size and typical reach — a proxy, not a quote.
              The risk read is a heuristic engagement-quality screen, not platform-verified fraud.
            </p>
          </Section>
        </Reveal>

        <Reveal delay={0.06}>
          <Section title="Growth">
            <ProjectionChart currentSubs={c.subscriber_count} forecast={forecast?.forecast ?? null} />
            <p className="mt-3 text-xs text-muted">
              Point = current measured subscribers. Dotted line = a 12-week projection scaled from
              the (simulated) niche-demand trend — not measured channel history. Per-channel
              longitudinal tracking accrues from the first daily snapshot onward.
            </p>
          </Section>
        </Reveal>

        <Reveal delay={0.06}>
          <Section title="Engagement quality">
            <dl className="grid grid-cols-2 gap-6 sm:grid-cols-4">
              <Stat label="Mean engagement rate" value={pctStr(c.mean_engagement_rate)} />
              <Stat
                label={`Percentile in ${peers?.niche ?? c.niche}${peers ? ` (n=${peers.cohort_size})` : ""}`}
                value={peers?.engagement_percentile == null ? "—" : `${Math.round(peers.engagement_percentile)}th`}
              />
              <Stat label="Like rate" value={pctStr(c.mean_like_rate)} />
              <Stat label="Comment rate" value={pctStr(c.mean_comment_rate)} />
            </dl>
            <p className="mt-4 text-xs text-muted">
              Engagement rate = (likes + comments) / views over observed videos. Percentile is
              within this creator&apos;s niche cohort. Consistency below.
            </p>
            <dl className="mt-4 grid grid-cols-2 gap-6 sm:grid-cols-4">
              <Stat label="Comment-to-like" value={pctStr(c.mean_comment_to_like_ratio)} />
              <Stat
                label="Engagement consistency (CV)"
                value={c.engagement_cv == null ? "—" : c.engagement_cv.toFixed(2)}
              />
              <Stat label="ER last 90d" value={pctStr(c.mean_engagement_rate_last_90d)} />
              <Stat label="Median ER" value={pctStr(c.median_engagement_rate)} />
            </dl>
          </Section>
        </Reveal>

        <Reveal delay={0.06}>
          <Section title="Output &amp; cadence">
            <dl className="grid grid-cols-2 gap-6 sm:grid-cols-4">
              <Stat label="Uploads last 30d" value={num(c.videos_last_30d)} />
              <Stat label="Uploads last 90d" value={num(c.videos_last_90d)} />
              <Stat
                label="Avg days between uploads"
                value={c.mean_inter_video_days == null ? "—" : c.mean_inter_video_days.toFixed(1)}
              />
              <Stat label="Avg video length" value={duration(c.mean_duration_seconds)} />
            </dl>
            <dl className="mt-4 grid grid-cols-2 gap-6 sm:grid-cols-4">
              <Stat label="Days since last upload" value={num(c.days_since_last_upload)} />
              <Stat
                label="Cadence consistency (±days)"
                value={c.std_inter_video_days == null ? "—" : c.std_inter_video_days.toFixed(1)}
              />
              <Stat label="Median views" value={compact(c.median_views)} />
              <Stat label="Avg views last 90d" value={compact(c.mean_views_last_90d)} />
            </dl>
          </Section>
        </Reveal>

        <Reveal delay={0.06}>
          <Section title={`Niche demand — ${c.niche}`}>
            {forecast && forecast.forecast.length >= 2 ? (
              <>
                <ForecastChart forecast={forecast.forecast} />
                <p className="mt-3 text-xs text-muted">
                  {direction && (
                    <>
                      <span className="text-ink">{c.niche}</span> is {direction} (size-weighted
                      trend slope).{" "}
                    </>
                  )}
                  Weekly views; the series is a simulated history (no real demand history yet), and
                  the 12 weeks right of the dashed line are the forecast with the 80% interval
                  shaded.
                </p>
              </>
            ) : (
              <p className="text-sm text-muted">No niche forecast available for {c.niche}.</p>
            )}
          </Section>
        </Reveal>

        {peers && peers.peers.length > 0 && (
          <Reveal delay={0.06}>
            <Section title={`Similar creators in ${peers.niche ?? c.niche}`}>
              <p className="mb-4 text-xs text-muted">
                Same niche, closest by average reach — click through to compare.
              </p>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {peers.peers.map((p) => (
                  <Link key={p.channel_id} href={`/creators/${p.channel_id}`} className="block">
                    <CreatorCard c={p} />
                  </Link>
                ))}
              </div>
            </Section>
          </Reveal>
        )}

        {peers && (
          <Reveal delay={0.06}>
            <Section title="Suggestions">
              <p className="mb-3 text-xs text-muted">
                Rule-based against {peers.niche ?? c.niche} medians — not ML.
              </p>
              {tips.length > 0 ? (
                <ul className="flex flex-col gap-2 text-sm text-ink">
                  {tips.map((t, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="text-violet">→</span>
                      <span>{t}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted">
                  At or above the {peers.niche ?? c.niche} median on cadence and engagement — keep
                  the current rhythm.
                </p>
              )}
            </Section>
          </Reveal>
        )}
      </div>
    </div>
  );
}
