import { cn } from "@/lib/utils";
import type { StackId } from "@/lib/mock/types";

export const STACK_LABEL: Record<StackId, string> = {
  nextjs: "Next.js",
  wordpress: "WordPress",
  angular: "Angular",
  vue: "Vue",
  react: "React",
  vite: "Vite",
  php: "PHP",
  other: "Autre",
};

/** Uniform, colourless — the label carries the meaning, not a tint. */
export function StackBadge({
  stack,
  label,
  className,
}: {
  stack: StackId;
  /** User-confirmed free-text stack — wins over the detected one. */
  label?: string | null;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-[18px] shrink-0 items-center rounded border border-hairline bg-white/[0.03] px-1.5 font-mono text-2xs text-ink-muted",
        className,
      )}
    >
      {label?.trim() || STACK_LABEL[stack]}
    </span>
  );
}
