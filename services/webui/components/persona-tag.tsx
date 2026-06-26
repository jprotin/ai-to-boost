import { Cpu, Sparkles } from "lucide-react";
import { modelLabel } from "@/lib/models";
import { cn } from "@/lib/utils";

// Tag « qui travaille » : persona BMAD + LLM derrière (Claude forfait vs modèle local).
export function PersonaTag({
  persona,
  model,
  compact,
  className,
}: {
  persona: string;
  model: string;
  compact?: boolean;
  className?: string;
}) {
  const isClaude = model === "claude";
  return (
    <span
      title={`${persona} · ${model}`}
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground",
        className,
      )}
    >
      {isClaude ? (
        <Sparkles className="size-3 shrink-0 text-violet-500" />
      ) : (
        <Cpu className="size-3 shrink-0 text-emerald-500" />
      )}
      {compact ? (
        <span className="shrink-0">{modelLabel(model)}</span>
      ) : (
        <>
          <span className="truncate">{persona}</span>
          <span className="shrink-0 opacity-70">· {modelLabel(model)}</span>
        </>
      )}
    </span>
  );
}
