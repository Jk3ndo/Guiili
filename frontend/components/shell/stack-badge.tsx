import { cn } from "@/lib/utils";
import type { StackId } from "@/lib/mock/types";

const LABEL: Record<StackId, string> = {
  nextjs: "Next.js",
  wordpress: "WordPress",
  angular: "Angular",
  vue: "Vue",
  other: "Autre",
};

/** Uniform, colourless — the label carries the meaning, not a tint. */
export function StackBadge({
  stack,
  className,
}: {
  stack: StackId;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-[18px] shrink-0 items-center rounded border border-hairline bg-white/[0.03] px-1.5 font-mono text-2xs text-ink-muted",
        className,
      )}
    >
      {LABEL[stack]}
    </span>
  );
}
