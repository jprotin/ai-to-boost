"use client";

import { useState } from "react";
import { StatusBadge } from "@/components/status-badge";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
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
      <Accordion
        multiple
        defaultValue={board.epics.map((e) => e.n)}
        className="rounded-lg border"
      >
        {board.epics.map((e) => (
          <AccordionItem key={e.n} value={e.n} className="px-4">
            <AccordionTrigger>
              <span className="flex items-center gap-2">
                <span className="font-medium">
                  Epic {e.n} — {e.title}
                </span>
                <StatusBadge status={e.status} />
                <span className="text-xs text-muted-foreground">
                  {e.stories.length} stories
                </span>
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <ul className="space-y-1 pb-2">
                {e.stories.map((s) => (
                  <li key={s.id}>
                    <button
                      onClick={() => setStory(s)}
                      className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent"
                    >
                      <span className="min-w-0 truncate">{s.title}</span>
                      <StatusBadge status={s.status} />
                    </button>
                  </li>
                ))}
              </ul>
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>

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
