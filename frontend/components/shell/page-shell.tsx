import { cn } from "@/lib/utils";

interface PageShellProps {
  /** Simple title (ignored when `header` is provided). */
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
  /** Full custom header, replaces the default title block. */
  header?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export function PageShell({
  title,
  subtitle,
  actions,
  header,
  children,
  className,
}: PageShellProps) {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-6 py-5">
      {header ?? (
        <header className="flex flex-wrap items-start justify-between gap-3 pb-5">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight text-ink">
              {title}
            </h1>
            {subtitle && (
              <p className="max-w-2xl text-sm text-ink-muted">{subtitle}</p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("space-y-4", className)}>{children}</div>
    </div>
  );
}
