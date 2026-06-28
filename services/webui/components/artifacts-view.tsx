"use client";

import { useCallback, useEffect, useState } from "react";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { Artifact } from "@/lib/api";

// Relecture des artefacts produits (brief/PRD/architecture/epics) avant approbation.
export function ArtifactsView({
  name,
  artifacts,
  current,
}: {
  name: string;
  artifacts: Artifact[];
  current?: string;
}) {
  const [selected, setSelected] = useState<string | undefined>(
    current && artifacts.some((a) => a.key === current)
      ? current
      : artifacts[artifacts.length - 1]?.key,
  );
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (key: string) => {
      setLoading(true);
      setError(null);
      try {
        const r = await fetch(
          `/api/projects/${encodeURIComponent(name)}/artifact/${encodeURIComponent(key)}`,
        );
        const d = await r.json();
        if (!r.ok) throw new Error(d?.error ?? "erreur");
        setContent(d.content ?? "");
      } catch (e) {
        setError(e instanceof Error ? e.message : "échec");
        setContent("");
      } finally {
        setLoading(false);
      }
    },
    [name],
  );

  useEffect(() => {
    if (selected) load(selected);
  }, [selected, load]);

  if (artifacts.length === 0) {
    return (
      <Card className="shadow-sm">
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          Aucun artefact produit pour l'instant.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {artifacts.map((a) => (
          <Button
            key={a.key}
            size="sm"
            variant={a.key === selected ? "default" : "outline"}
            onClick={() => setSelected(a.key)}
          >
            {a.title}
          </Button>
        ))}
      </div>
      <Card className="shadow-sm">
        <CardContent className="py-4">
          {loading ? (
            <p className="text-sm text-muted-foreground">Chargement…</p>
          ) : error ? (
            <p className="text-sm text-destructive">{error}</p>
          ) : content.trim() ? (
            <Markdown>{content}</Markdown>
          ) : (
            <p className="text-sm text-muted-foreground">Artefact vide.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
