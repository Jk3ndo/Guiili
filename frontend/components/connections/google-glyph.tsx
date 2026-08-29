import { cn } from "@/lib/utils";

/** Monochrome Google "G" mark — inherits `currentColor`, no brand colours. */
export function GoogleGlyph({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      className={cn("size-3.5", className)}
    >
      <path d="M12 10.2v3.9h5.45c-.24 1.4-1.66 4.12-5.45 4.12-3.28 0-5.96-2.72-5.96-6.07S8.72 6.08 12 6.08c1.87 0 3.12.8 3.84 1.48l2.62-2.52C16.78 3.5 14.62 2.5 12 2.5 6.76 2.5 2.5 6.76 2.5 12S6.76 21.5 12 21.5c5.48 0 9.1-3.85 9.1-9.27 0-.62-.07-1.1-.15-1.58H12z" />
    </svg>
  );
}
