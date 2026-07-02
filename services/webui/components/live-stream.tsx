"use client";

import { Activity } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type Ev = { seq: number; kind: string; text: string; story?: string | null };

// Popup « Voir en direct » : poll le flux live du pipeline (~1,2 s) et affiche les
// actions de l'IA au fil de l'eau (marqueur story, outils, texte). Polling-tail.
export function LiveStream({ name }: { name: string }) {
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState<Ev[]>([]);
  const sinceRef = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    async function tick() {
      try {
        const r = await fetch(
          `/api/projects/${encodeURIComponent(name)}/live?since=${sinceRef.current}`,
        );
        const d = await r.json();
        if (typeof d.next === "number") sinceRef.current = d.next;
        if (alive && Array.isArray(d.events) && d.events.length) {
          setEvents((prev) => [...prev, ...d.events].slice(-500));
        }
      } catch {
        /* silencieux : on retentera au prochain tick */
      }
    }
    tick();
    const id = setInterval(tick, 1200);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [open, name]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) {
          setEvents([]); // repart propre à chaque ouverture (reset hors effet)
          sinceRef.current = 0;
        }
      }}
    >
      <DialogTrigger
        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-2")}
      >
        <Activity className="size-4" />
        Voir en direct
      </DialogTrigger>
      <DialogContent className="max-w-2xl sm:max-w-3xl lg:max-w-5xl xl:max-w-6xl">
        <DialogHeader>
          <DialogTitle>Déroulement en direct</DialogTitle>
        </DialogHeader>
        <div className="max-h-[70vh] space-y-1 overflow-auto rounded-md bg-muted p-3 font-mono text-xs">
          {events.length === 0 ? (
            <p className="text-muted-foreground">
              En attente d&apos;activité de l&apos;IA…
            </p>
          ) : (
            events.map((e) => (
              <div
                key={e.seq}
                className={cn(
                  e.kind === "phase" && "mt-2 font-semibold text-foreground",
                  e.kind === "tool" && "text-primary",
                  e.kind === "text" &&
                    "whitespace-pre-wrap text-muted-foreground",
                )}
              >
                {e.text}
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
