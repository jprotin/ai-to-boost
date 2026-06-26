"use client";

import { Rocket } from "lucide-react";
import { useRouter } from "next/navigation";
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
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

export function LaunchPipeline({ name }: { name: string }) {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function run() {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(name)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d?.error ?? "erreur");
      toast.success(`Pipeline lancé (${d.pipeline_id})`);
      setOpen(false);
      setPrompt("");
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "échec du lancement");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        <Rocket className="size-4" />
        Lancer un pipeline
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Lancer un pipeline BMAD</DialogTitle>
          <DialogDescription>
            Décrivez le besoin — le pipeline démarre sur le projet « {name} »
            (analyst → PM → architecte → epics → implémentation).
          </DialogDescription>
        </DialogHeader>
        <Textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Ex. une page HTML qui affiche l'heure de Paris en temps réel"
          className="min-h-[7rem]"
        />
        <DialogFooter>
          <Button onClick={run} disabled={loading || !prompt.trim()}>
            {loading ? "Lancement…" : "Lancer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
