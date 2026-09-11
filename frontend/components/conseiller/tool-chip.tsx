export function ToolChip({ tool }: { tool: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-1 text-2xs text-ink-faint">
      <span className="size-1 rounded-full bg-ink-faint" />
      {tool}
    </span>
  );
}
