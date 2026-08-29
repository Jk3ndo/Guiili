import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** A bordered surface card at a fixed height — reserves layout up front. */
function Card({
  className,
  children,
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-hairline bg-surface p-4",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function KpiRowSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i} className="h-[92px] space-y-2.5">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-6 w-16" />
          <Skeleton className="h-3 w-20" />
        </Card>
      ))}
    </div>
  );
}

export function ChartSkeleton({ label }: { label?: string }) {
  return (
    <Card className="flex h-full flex-col gap-3">
      <div className="flex items-center justify-between">
        <Skeleton className="h-3.5 w-40" />
        <Skeleton className="h-7 w-28" />
      </div>
      <Skeleton className="min-h-[220px] flex-1" />
      {label && <p className="text-2xs text-ink-faint">{label}</p>}
    </Card>
  );
}

export function DonutSkeleton({ label }: { label?: string }) {
  return (
    <Card className="flex h-full flex-col gap-3">
      <Skeleton className="h-3.5 w-40" />
      <div className="flex flex-1 items-center justify-center py-4">
        <Skeleton className="size-32 rounded-full border-8 border-white/[0.04] bg-transparent" />
      </div>
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex items-center gap-2">
            <Skeleton className="size-2.5 rounded-full" />
            <Skeleton className="h-3 w-24" />
            <Skeleton className="ml-auto h-3 w-8" />
          </div>
        ))}
      </div>
      {label && <p className="text-2xs text-ink-faint">{label}</p>}
    </Card>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <Card className="p-0">
      <div className="flex items-center gap-4 border-b border-hairline px-4 py-2.5">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="ml-auto h-3 w-16" />
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-16" />
      </div>
      <div className="divide-y divide-hairline">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-3">
            <Skeleton className="h-3.5 w-56" />
            <Skeleton className="ml-auto h-3.5 w-12" />
            <Skeleton className="h-3.5 w-12" />
            <Skeleton className="h-3.5 w-12" />
          </div>
        ))}
      </div>
    </Card>
  );
}

export function CardGridSkeleton({
  count = 3,
  height = "h-[132px]",
}: {
  count?: number;
  height?: string;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i} className={cn(height, "space-y-3")}>
          <div className="flex items-center gap-2.5">
            <Skeleton className="size-8 rounded-md" />
            <div className="space-y-1.5">
              <Skeleton className="h-3.5 w-32" />
              <Skeleton className="h-3 w-20" />
            </div>
          </div>
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-2/3" />
        </Card>
      ))}
    </div>
  );
}

export function BoardSkeleton({
  columns = ["À faire", "En cours", "Corrigé"],
}: {
  columns?: string[];
}) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {columns.map((col) => (
        <div
          key={col}
          className="flex min-h-[320px] flex-col rounded-lg border border-hairline bg-surface"
        >
          <div className="flex items-center justify-between border-b border-hairline px-3 py-2.5">
            <span className="text-xs font-medium text-ink-muted">{col}</span>
            <Skeleton className="h-4 w-6 rounded-full" />
          </div>
          <div className="space-y-2 p-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="space-y-2 rounded-md border border-hairline bg-raised p-3"
              >
                <Skeleton className="h-3.5 w-4/5" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
