"use client";

import { useState } from "react";
import { StatusBadge } from "@/components/status-badge";
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
                <StatusBadge status={e.status} />
              </div>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {e.stories.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setStory(s)}
                  className="flex w-full items-center justify-between gap-2 rounded-md border bg-background px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
                >
                  <span className="min-w-0 truncate">{s.title}</span>
                  <StatusBadge status={s.status} />
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
            </DialogDescription>
          </DialogHeader>
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">
            {story?.detail?.trim() || "Aucun détail enregistré pour cette story."}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  );
}
