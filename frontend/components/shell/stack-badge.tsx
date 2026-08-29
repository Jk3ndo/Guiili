import { cn } from "@/lib/utils";
import type { StackId } from "@/lib/mock/types";

const STACK_META: Record<StackId, { label: string; className: string }> = {
  nextjs: {
    label: "Next.js",
    className: "border-indigo/25 bg-indigo/10 text-indigo",
  },
  wordpress: {
    label: "WordPress",
    className: "border-hairline-strong bg-white/5 text-ink-muted",
  },
  angular: {
    label: "Angular",
    className: "border-danger/25 bg-danger/10 text-danger",
  },
  vue: {
    label: "Vue",
    className: "border-ok/25 bg-ok/10 text-ok",
  },
  other: {
    label: "Autre",
    className: "border-hairline-strong bg-white/5 text-ink-faint",
  },
};

export function StackBadge({
  stack,
  className,
}: {
  stack: StackId;
  className?: string;
}) {
  const meta = STACK_META[stack];
  return (
    <span
      className={cn(
        "inline-flex h-[18px] shrink-0 items-center rounded-full border px-1.5 text-2xs font-medium tracking-wide",
        meta.className,
        className,
      )}
    >
      {meta.label}
    </span>
  );
}
