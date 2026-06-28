"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Crée un projet pilotable depuis la webui (git + develop + marqueur via le worker).
export function CreateProjectDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");

  async function create() {
    setBusy(true);
    try {
      const r = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), path: path.trim() || undefined }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d?.error ?? "échec de la création");
      toast.success(`Projet « ${d.name} » créé`);
      setOpen(false);
      setName("");
      setPath("");
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "échec");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger className={buttonVariants({ size: "sm" })}>
        Nouveau projet
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nouveau projet</DialogTitle>
          <DialogDescription>
            Crée un dépôt git (main + develop) initialisé pour BMAD. Le chemin par
            défaut est <code className="text-xs">~/dev/&lt;nom&gt;</code>.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="proj-name">Nom</Label>
            <Input
              id="proj-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="mon-projet"
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="proj-path">Chemin (optionnel)</Label>
            <Input
              id="proj-path"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="~/dev/mon-projet"
            />
          </div>
        </div>
        <DialogFooter>
          <Button disabled={busy || !name.trim()} onClick={create}>
            Créer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
