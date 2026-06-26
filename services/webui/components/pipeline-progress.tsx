"use client";

import { Check, Clock, Loader2 } from "lucide-react";
import type { Phase } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PersonaTag } from "@/components/persona-tag";
import { Card, CardContent } from "@/components/ui/card";

const PHASES = [
  { key: "analyst", label: "Analyse" },
  { key: "pm", label: "PRD" },
  { key: "architect", label: "Architecture" },
  { key: "epics", label: "Epics" },
  { key: "implementation", label: "Implémentation" },
];

export function PipelineProgress({
  status,
  phase,
  phases,
}: {
  status?: string;
  phase?: string;
  phases?: Phase[];
}) {
  // Affiché seulement tant que le pipeline est en cours / en attente.
  if (!status || !["accepted", "running", "awaiting_approval"].includes(status)) {
    return null;
  }
  const idx = PHASES.findIndex((p) => p.key === phase);
  const running = status === "running" || status === "accepted";
  const awaiting = status === "awaiting_approval";
  const label = PHASES[idx]?.label ?? phase ?? "…";
  const active = phases?.find((p) => p.key === phase);

  return (
    <Card className="shadow-sm">
      <CardContent className="space-y-3 py-4">
        <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {running ? (
            <>
              <Loader2 className="size-4 animate-spin text-primary" />
              L&apos;agent travaille — phase « {label} »…
            </>
          ) : (
            <>
              <Clock className="size-4 text-amber-500" />
              Jalon « {label} » — en attente de votre validation
            </>
          )}
          {active ? (
            <PersonaTag persona={active.persona} model={active.model} />
          ) : null}
        </div>
        {running ? (
          <p className="text-xs text-muted-foreground">
            Cela peut prendre d&apos;une à deux minutes selon la phase — vous
            pouvez quitter, la progression continue.
          </p>
        ) : null}

        <ol className="flex flex-wrap items-center gap-1.5">
          {PHASES.map((p, i) => {
            const done = idx >= 0 && i < idx;
            const current = i === idx;
            return (
              <li
                key={p.key}
                className={cn(
                  "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
                  done && "border-primary/30 bg-primary/5 text-foreground",
                  current &&
                    (awaiting
                      ? "border-amber-500/40 bg-amber-500/10 font-medium"
                      : "border-primary/40 bg-primary/10 font-medium"),
                  !done && !current && "text-muted-foreground",
                )}
              >
                {done ? (
                  <Check className="size-3 text-primary" />
                ) : current && running ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : current && awaiting ? (
                  <Clock className="size-3 text-amber-500" />
                ) : (
                  <span className="size-3 rounded-full border" />
                )}
                {p.label}
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}
