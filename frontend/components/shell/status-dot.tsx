import { cn } from "@/lib/utils";
import type { TokenStatus } from "@/lib/mock/types";

const COLOR: Record<TokenStatus, string> = {
  connected: "bg-ok",
  needs_reauth: "bg-warn",
};

/** Flat 6px dot. No pulse, no glow. */
export function StatusDot({
  status,
  className,
}: {
  status: TokenStatus;
  className?: string;
}) {
  return (
    <span
      className={cn("size-1.5 shrink-0 rounded-full", COLOR[status], className)}
    />
  );
}
