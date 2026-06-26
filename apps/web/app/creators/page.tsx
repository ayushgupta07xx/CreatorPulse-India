"use client";

import { useEffect, useState } from "react";
import SkeletonGrid from "@/components/SkeletonGrid";
import Link from "next/link";
import { searchCreators, type CreatorSummary } from "@/lib/api";
import CreatorCard from "@/components/CreatorCard";
import Reveal from "@/components/Reveal";

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "done"; results: CreatorSummary[] }
  | { kind: "error"; message: string };

export default function CreatorsPage() {
  const [q, setQ] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });

  async function run(initial?: string) {
    const term = (initial ?? q).trim();
    if (!term) return;
    setState({ kind: "loading" });
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}?q=${encodeURIComponent(term)}`,
    );
    try {
      const results = await searchCreators(term, 24);
      setState({ kind: "done", results });
    } catch (e) {
      setState({
        kind: "error",
        message: e instanceof Error ? e.message : "Search failed",
      });
    }
  }

  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("q");
    if (initial) {
      setQ(initial);
      run(initial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="mx-auto max-w-wrap px-6 py-12">
      <Reveal>
        <h1 className="font-display text-3xl font-bold tracking-tight text-ink sm:text-4xl">
          Search creators
        </h1>
        <p className="mt-3 max-w-xl text-muted">
          Type a channel name. Each result shows reach, an estimated sponsored
          cost, and an engagement-risk read.
        </p>
      </Reveal>

      <Reveal delay={0.06}>
        <div className="mt-8 flex gap-3">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
            placeholder="e.g. CarryMinati"
            aria-label="Creator name"
            className="w-full rounded-xl border border-white/10 bg-surface/60 px-4 py-3 text-ink placeholder:text-muted focus:border-violet focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet"
          />
          <button
            onClick={() => run()}
            className="btn-sheen shrink-0 rounded-xl bg-ink px-6 py-3 text-sm font-semibold text-bg transition-transform hover:-translate-y-0.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet"
          >
            Search
          </button>
        </div>
      </Reveal>

      <div className="mt-10">
        {state.kind === "loading" && <SkeletonGrid variant="creator" count={6} />}

        {state.kind === "error" && (
          <p className="text-risk-high">
            Couldn&apos;t reach the search service ({state.message}). Try again in
            a moment.
          </p>
        )}

        {state.kind === "done" && state.results.length === 0 && (
          <p className="text-muted">
            “{q.trim()}” isn’t in CreatorPulse’s index. The catalogue is a
            fixed set of Indian creators, so not every channel is covered —
            try another name.
          </p>
        )}

        {state.kind === "done" && state.results.length > 0 && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {state.results.map((c, i) => (
              <Reveal key={c.channel_id} delay={Math.min(i * 0.04, 0.4)}>
                <Link href={`/creators/${c.channel_id}`} className="block">
                  <CreatorCard c={c} />
                </Link>
              </Reveal>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
