"use client";

import { useState } from "react";
import { Markdown } from "@/components/markdown";
import { PersonaTag } from "@/components/persona-tag";
import { StatusBadge } from "@/components/status-badge";
import { TokenStat } from "@/components/token-stat";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Board, Story } from "@/lib/api";

export function ProjectBoard({ board }: { board: Board }) {
  const [story, setStory] = useState<Story | null>(null);
  const epicsPhase = board.phases?.find((p) => p.key === "epics");
  const implPhase = board.phases?.find((p) => p.key === "implementation");

  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        {board.epics.map((e) => (
          <Card key={e.n} className="shadow-sm">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-base">
                  Epic {e.n} — {e.title}
                </CardTitle>
                <span className="flex shrink-0 items-center gap-2">
                  <TokenStat tokens={e.tokens} />
                  <StatusBadge status={e.status} />
                </span>
              </div>
              {epicsPhase ? (
                <PersonaTag
                  persona={epicsPhase.persona}
                  model={epicsPhase.model}
                  className="mt-1 w-fit"
                />
              ) : null}
            </CardHeader>
            <CardContent className="space-y-1.5">
              {e.stories.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setStory(s)}
                  className="flex w-full items-center justify-between gap-2 rounded-md border bg-background px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
                >
                  <span className="min-w-0 truncate">{s.title}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    <TokenStat tokens={s.tokens} />
                    {s.status !== "backlog" && implPhase ? (
                      <PersonaTag
                        persona={implPhase.persona}
                        model={implPhase.model}
                        compact
                      />
                    ) : null}
                    <StatusBadge status={s.status} />
                  </span>
                </button>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={Boolean(story)} onOpenChange={(o) => !o && setStory(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{story?.title}</DialogTitle>
            <DialogDescription className="flex items-center gap-2">
              <StatusBadge status={story?.status} />
              <code className="text-xs">{story?.id}</code>
              <TokenStat tokens={story?.tokens} />
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-auto rounded-md bg-muted p-3">
            {story?.detail?.trim() ? (
              <Markdown>{story.detail}</Markdown>
            ) : (
              <p className="text-sm text-muted-foreground">
                Aucun détail enregistré pour cette story.
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
