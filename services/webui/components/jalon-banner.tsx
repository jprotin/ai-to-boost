"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

export function JalonBanner({
  name,
  phase,
  onResolved,
}: {
  name: string;
  phase?: string;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [reviseOpen, setReviseOpen] = useState(false);
  const [feedback, setFeedback] = useState("");

  async function resume(decision: string) {
    setBusy(true);
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(name)}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d?.error ?? "erreur");
      toast.success(`${decision.split(":")[0]} envoyé`);
      setReviseOpen(false);
      setFeedback("");
      onResolved();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "échec");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
      <span className="font-medium">
        ⏸ Jalon « {phase ?? "?"} » — en attente de validation
      </span>
      <div className="ml-auto flex gap-2">
        <Button size="sm" disabled={busy} onClick={() => resume("approve")}>
          Approuver
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => setReviseOpen(true)}
        >
          Réviser
        </Button>
        <Button
          size="sm"
          variant="destructive"
          disabled={busy}
          onClick={() => resume("stop")}
        >
          Arrêter
        </Button>
      </div>

      <Dialog open={reviseOpen} onOpenChange={setReviseOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Réviser la phase « {phase ?? "?"} »</DialogTitle>
            <DialogDescription>
              Votre retour est intégré et la phase est rejouée.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="Ce qu'il faut corriger…"
            className="min-h-[6rem]"
          />
          <DialogFooter>
            <Button
              disabled={busy || !feedback.trim()}
              onClick={() => resume(`revise:${feedback.trim()}`)}
            >
              Envoyer le retour
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
