import { ArrowDown, ArrowUp } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Tokens } from "@/lib/api";

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

// Affiche la consommation de tokens (entrée ↑ / sortie ↓). Rien si absent/nul.
export function TokenStat({
  tokens,
  className,
}: {
  tokens?: Tokens | null;
  className?: string;
}) {
  if (!tokens || (!tokens.input && !tokens.output)) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground",
        className,
      )}
      title={`Tokens — entrée ${tokens.input.toLocaleString("fr")}, sortie ${tokens.output.toLocaleString("fr")}`}
    >
      <span className="inline-flex items-center gap-0.5">
        <ArrowUp className="size-3" />
        {fmt(tokens.input)}
      </span>
      <span className="inline-flex items-center gap-0.5">
        <ArrowDown className="size-3" />
        {fmt(tokens.output)}
      </span>
    </span>
  );
}
