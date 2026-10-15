import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden="true">
        <rect width="32" height="32" rx="8" className="fill-primary" />
        <circle cx="14" cy="14" r="6.5" fill="none" stroke="white" strokeWidth="2.5" />
        <path d="M19 19l5.5 5.5" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
      <span className="text-base">TalentLens</span>
    </span>
  );
}
