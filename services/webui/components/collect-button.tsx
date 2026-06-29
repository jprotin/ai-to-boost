"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { buttonVariants } from "@/components/ui/button";

// Intègre la branche pipeline du projet dans sa base (merge --no-ff via le worker).
export function CollectButton({
  name,
  base,
  branch,
  onCollected,
}: {
  name: string;
  base?: string;
  branch?: string;
  onCollected: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  async function collect() {
    setBusy(true);
    try {
      const r = await fetch(
        `/api/projects/${encodeURIComponent(name)}/collect`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        },
      );
      const d = await r.json();
      if (!r.ok) throw new Error(d?.error ?? "échec de l'intégration");
      toast.success(`Intégré : ${d.branch} → ${d.base}`);
      setOpen(false);
      onCollected();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "échec");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger
        className={buttonVariants({ size: "sm" })}
        disabled={busy}
      >
        Récupérer le résultat
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Intégrer le résultat du pipeline ?</AlertDialogTitle>
          <AlertDialogDescription>
            Le travail de la branche{" "}
            <code className="text-xs">{branch ?? "pipeline/…"}</code> sera fusionné
            dans <code className="text-xs">{base ?? "la base du projet"}</code> (merge
            --no-ff). Opération git locale, non poussée.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Annuler</AlertDialogCancel>
          <AlertDialogAction disabled={busy} onClick={collect}>
            Intégrer
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
