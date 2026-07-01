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
import { MicButton } from "@/components/mic-button";

export function LaunchPipeline({
  name,
  onLaunched,
}: {
  name: string;
  onLaunched?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState<"sonnet" | "opus">("sonnet");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function run() {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(name)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, dev_model: model }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d?.error ?? "erreur");
      toast.success(`Pipeline lancé (${d.pipeline_id})`);
      setOpen(false);
      setPrompt("");
      onLaunched?.(); // rafraîchit le board client + démarre le polling live
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
        <div className="flex items-start gap-2">
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Ex. une page HTML qui affiche l'heure de Paris en temps réel"
            className="min-h-[7rem] flex-1"
          />
          <MicButton
            disabled={loading}
            onTranscript={(t) =>
              setPrompt((prev) => (prev ? `${prev} ${t}` : t))
            }
          />
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Modèle dev :</span>
          <Button
            type="button"
            size="sm"
            variant={model === "sonnet" ? "default" : "outline"}
            onClick={() => setModel("sonnet")}
          >
            Rapide (Sonnet)
          </Button>
          <Button
            type="button"
            size="sm"
            variant={model === "opus" ? "default" : "outline"}
            onClick={() => setModel("opus")}
          >
            Qualité (Opus)
          </Button>
        </div>
        <DialogFooter>
          <Button onClick={run} disabled={loading || !prompt.trim()}>
            {loading ? "Lancement…" : "Lancer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
