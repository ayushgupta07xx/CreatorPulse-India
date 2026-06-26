// Loading skeletons. Reuses the global .shimmer animation (globals.css) and the
// same gradient-border card wrapper as BrandResultCard / CreatorCard so the
// loading state is pixel-matched to the real content (no layout shift on load).

function Block({ className = "" }: { className?: string }) {
  return <div className={`shimmer rounded-md bg-white/[0.04] ${className}`} />;
}

// Mirrors the card wrapper: rounded-2xl gradient p-px -> inner rounded-[15px] bg-surface/90 p-5.
function CardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-gradient-to-br from-violet/20 via-teal/10 to-white/5 p-px">
      <div className="flex h-full flex-col rounded-[15px] bg-surface/90 p-5">{children}</div>
    </div>
  );
}

function CreatorCardSkeleton() {
  return (
    <CardShell>
      <div className="flex items-center gap-3">
        <Block className="h-12 w-12 shrink-0 rounded-full" />
        <div className="min-w-0 flex-1 space-y-2">
          <Block className="h-4 w-3/4" />
          <Block className="h-3 w-1/3" />
        </div>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-3">
        <Block className="h-3 w-full" />
        <Block className="h-3 w-full" />
        <Block className="h-3 w-2/3" />
        <Block className="h-3 w-2/3" />
      </div>
      <Block className="mt-5 h-9 w-full rounded-xl" />
    </CardShell>
  );
}

function BrandResultCardSkeleton() {
  return (
    <CardShell>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Block className="h-12 w-12 shrink-0 rounded-full" />
          <div className="space-y-2">
            <Block className="h-4 w-32" />
            <Block className="h-3 w-20" />
          </div>
        </div>
        <Block className="h-7 w-10 rounded-md" />
      </div>
      <div className="mt-5 flex gap-5">
        <Block className="h-28 w-28 shrink-0 rounded-full" />
        <div className="flex-1 space-y-3 pt-1">
          <Block className="h-3 w-full" />
          <Block className="h-3 w-5/6" />
          <Block className="h-3 w-4/6" />
          <Block className="h-3 w-3/6" />
        </div>
      </div>
      <Block className="mt-5 h-9 w-full rounded-xl" />
    </CardShell>
  );
}

/** Grid of skeleton cards. variant picks card shape + column count to match the real grid. */
export default function SkeletonGrid({
  variant,
  count = 4,
}: {
  variant: "brand" | "creator";
  count?: number;
}) {
  const cols =
    variant === "brand"
      ? "grid-cols-1 lg:grid-cols-2"
      : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3";
  const Card = variant === "brand" ? BrandResultCardSkeleton : CreatorCardSkeleton;
  return (
    <div className={`mt-6 grid gap-4 ${cols}`} aria-busy="true" aria-live="polite">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i} />
      ))}
    </div>
  );
}
