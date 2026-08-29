import { cn } from "@/lib/utils";
import type { TokenStatus } from "@/lib/mock/types";

const DOT: Record<TokenStatus, { color: string; pulse: boolean }> = {
  connected: { color: "bg-ok", pulse: false },
  needs_reauth: { color: "bg-warn", pulse: true },
};

export function StatusDot({
  status,
  className,
}: {
  status: TokenStatus;
  className?: string;
}) {
  const { color, pulse } = DOT[status];
  return (
    <span className={cn("relative flex size-2 shrink-0", className)}>
      {pulse && (
        <span
          className={cn(
            "absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:hidden",
            color,
          )}
        />
      )}
      <span className={cn("relative inline-flex size-2 rounded-full", color)} />
    </span>
  );
}
