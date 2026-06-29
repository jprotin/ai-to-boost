"use client";

import { useCallback, useEffect, useState } from "react";
import { ArtifactsView } from "@/components/artifacts-view";
import { ProjectBoard } from "@/components/project-board";
import { StatusBadge } from "@/components/status-badge";
import { TokenStat } from "@/components/token-stat";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { Board, Tokens } from "@/lib/api";

type Run = {
  id: string;
  prompt?: string;
  status?: string;
  created?: string;
  finished?: string;
  branch?: string;
  tokens?: Tokens | null;
};

// "2026-06-29T10:00:00" -> "29/06 10:00" (vide -> "—").
function fmtDate(iso?: string): string {
  if (!iso) return "—";
  const [date, time] = iso.split("T");
  const [y, mo, da] = date.split("-");
  return `${da}/${mo}/${y} ${(time ?? "").slice(0, 5)}`.trim();
}

// Archive : runs passés d'un projet (PRD/architecture/epics/stories déjà réalisés).
export function ArchiveView({ name }: { name: string }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`/api/projects/${encodeURIComponent(name)}/history`)
      .then((r) => r.json())
      .then((d) => setRuns(Array.isArray(d.runs) ? d.runs : []))
      .catch(() => setRuns([]));
  }, [name]);

  const open = useCallback(
    async (pid: string) => {
      setSelected(pid);
      setLoading(true);
      setBoard(null);
      try {
        const r = await fetch(
          `/api/projects/${encodeURIComponent(name)}/history/${encodeURIComponent(pid)}`,
        );
        if (r.ok) setBoard(await r.json());
      } catch {
        /* silencieux */
      } finally {
        setLoading(false);
      }
    },
    [name],
  );

  if (runs === null) {
    return <p className="text-sm text-muted-foreground">Chargement…</p>;
  }
  if (runs.length === 0) {
    return (
      <Card className="shadow-sm">
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          Aucun run archivé. L&apos;historique se remplit à chaque pipeline lancé.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        {runs.map((run) => (
          <button
            key={run.id}
            onClick={() => open(run.id)}
            className={`flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-accent ${
              run.id === selected ? "border-ring bg-accent" : "bg-background"
            }`}
          >
            <span className="min-w-0">
              <span className="block truncate font-medium">
                {run.prompt || "(sans description)"}
              </span>
              <span className="text-xs text-muted-foreground">
                Créé {fmtDate(run.created)}
                {run.finished ? ` · Terminé ${fmtDate(run.finished)}` : ""}
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <TokenStat tokens={run.tokens} />
              <StatusBadge status={run.status} />
            </span>
          </button>
        ))}
      </div>

      {selected ? (
        loading ? (
          <p className="text-sm text-muted-foreground">Chargement du run…</p>
        ) : board ? (
          <div className="space-y-4 rounded-lg border bg-muted/30 p-3">
            <ArtifactsView
              name={name}
              pid={selected}
              artifacts={board.pipeline?.artifacts ?? []}
            />
            {board.epics.length ? <ProjectBoard board={board} /> : null}
          </div>
        ) : (
          <p className="text-sm text-destructive">Run illisible (branche supprimée ?).</p>
        )
      ) : null}
    </div>
  );
}
