// Designed empty / error state: centered icon-in-circle + title + muted body.
// tone="neutral" for no-results, tone="error" for failures. Uses theme tokens.

import type { ReactNode } from "react";

type Tone = "neutral" | "error";

export default function EmptyState({
  icon,
  title,
  body,
  tone = "neutral",
}: {
  icon: ReactNode;
  title: string;
  body: ReactNode;
  tone?: Tone;
}) {
  const ring =
    tone === "error"
      ? "border-risk-high/30 bg-risk-high/10 text-risk-high"
      : "border-white/10 bg-white/[0.03] text-muted";
  return (
    <div className="mt-10 flex flex-col items-center justify-center px-6 py-12 text-center">
      <div
        className={`flex h-14 w-14 items-center justify-center rounded-2xl border ${ring}`}
        aria-hidden
      >
        {icon}
      </div>
      <p className="mt-5 font-display text-lg font-semibold text-ink">{title}</p>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">{body}</p>
    </div>
  );
}

// Small inline icons (stroke=currentColor so tone color applies).
export function SearchOffIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3M8 11h6" />
    </svg>
  );
}

export function AlertIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 9v4M12 17h.01" />
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    </svg>
  );
}

export function InboxIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 12h-6l-2 3h-4l-2-3H2" />
      <path d="M5.5 5.5 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.5A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.5Z" />
    </svg>
  );
}
