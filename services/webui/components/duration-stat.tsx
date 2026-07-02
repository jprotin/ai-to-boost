import { Clock } from "lucide-react";
import { cn } from "@/lib/utils";

// Formate une durée en secondes → compact humain (45s / 3m12 / 1h05).
export function fmtDuration(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m${String(Math.round(s % 60)).padStart(2, "0")}`;
  const h = Math.floor(m / 60);
  return `${h}h${String(m % 60).padStart(2, "0")}`;
}

// Affiche une durée (secondes). Rien si absent/nul.
export function DurationStat({
  seconds,
  title,
  className,
}: {
  seconds?: number | null;
  title?: string;
  className?: string;
}) {
  if (seconds == null || seconds <= 0) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 font-mono text-xs text-muted-foreground",
        className,
      )}
      title={title ?? `Durée : ${fmtDuration(seconds)}`}
    >
      <Clock className="size-3" />
      {fmtDuration(seconds)}
    </span>
  );
}
