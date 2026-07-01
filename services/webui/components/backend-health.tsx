"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";

type Health = { worker: boolean; bridge: boolean; litellm: boolean };

const ROWS: { key: keyof Health; label: string }[] = [
  { key: "worker", label: "Worker (pipelines / projets)" },
  { key: "bridge", label: "Bridge (Claude forfait)" },
  { key: "litellm", label: "LiteLLM (modèles locaux)" },
];

// Santé des backends chargée APRÈS le montage (via /api/health) : la page Settings
// s'affiche instantanément, les badges se remplissent en arrière-plan.
export function BackendHealth() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (alive && d) setHealth(d as Health);
      })
      .catch(() => {
        /* silencieux : badges restent en « vérification » */
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="space-y-2 text-sm">
      {ROWS.map((row) => (
        <div key={row.key} className="flex items-center justify-between">
          <span>{row.label}</span>
          {health === null ? (
            <Badge variant="secondary">
              <Loader2 className="size-3 animate-spin" /> vérification…
            </Badge>
          ) : health[row.key] ? (
            <Badge variant="default">OK</Badge>
          ) : (
            <Badge variant="destructive">indisponible</Badge>
          )}
        </div>
      ))}
    </div>
  );
}
