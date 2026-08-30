import type { VitalRating, WebVital } from "@/lib/mock/audit";
import { cn } from "@/lib/utils";

const MARKER: Record<VitalRating, string> = {
  good: "bg-ok",
  warn: "bg-warn",
  bad: "bg-danger",
};

function pct(value: number, max: number): number {
  return Math.min(100, Math.max(0, (value / max) * 100));
}

/** Thin segmented track (good / needs-improvement / poor) with a value marker. */
export function VitalGauge({
  vital,
  className,
}: {
  vital: WebVital;
  className?: string;
}) {
  const [good, poor] = vital.thresholds;
  const max = poor * 1.6;

  const goodWidth = pct(good, max);
  const warnWidth = pct(poor - good, max);
  const badWidth = Math.max(0, 100 - goodWidth - warnWidth);
  const markerLeft = pct(vital.raw, max);

  return (
    <div className={cn("relative", className)}>
      <div className="flex h-1 overflow-hidden rounded-full">
        <div className="bg-ok/30" style={{ width: `${goodWidth}%` }} />
        <div className="bg-warn/30" style={{ width: `${warnWidth}%` }} />
        <div className="bg-danger/30" style={{ width: `${badWidth}%` }} />
      </div>
      <span
        className={cn(
          "absolute top-1/2 h-2.5 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full",
          MARKER[vital.rating],
        )}
        style={{ left: `${markerLeft}%` }}
      />
    </div>
  );
}
