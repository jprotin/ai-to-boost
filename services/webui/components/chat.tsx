"use client";

import {
  Check,
  Download,
  Loader2,
  MessagesSquare,
  Pencil,
  Rocket,
  Send,
  Square,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  ConversationList,
  type Conversation,
} from "@/components/conversation-list";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { MicButton } from "@/components/mic-button";

type Msg = { role: "user" | "assistant"; content: string };
type Model = { id: string; label: string };

export function Chat({
  project,
  pipeline,
  onPipelineAction,
}: {
  project?: string;
  pipeline?: { status?: string; phase?: string };
  onPipelineAction?: () => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  // Étiquette de mode du chat projet : discuter (LLM) ou développer (lance le
  // pipeline). `revising` = état transitoire déclenché par le bouton « Réviser ».
  const [mode, setMode] = useState<"chat" | "develop">("chat");
  const [revising, setRevising] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const status = pipeline?.status;
  const pipelineActive =
    status === "accepted" ||
    status === "running" ||
    status === "awaiting_approval";

  const refreshConversations = useCallback(async () => {
    try {
      const url = project
        ? `/api/conversations?project=${encodeURIComponent(project)}`
        : "/api/conversations";
      const r = await fetch(url);
      const d = await r.json();
      setConversations(d?.conversations ?? []);
    } catch {
      /* silencieux */
    }
  }, [project]);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/models");
        const d = await r.json();
        const list: Model[] = d?.models ?? [];
        setModels(list);
        setModel((m) => m || list[0]?.id || "");
      } catch {
        setModels([]);
      }
      await refreshConversations();
    })();
  }, [refreshConversations]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  function newConversation() {
    setActiveId(null);
    setMessages([]);
    setSheetOpen(false);
  }

  async function openConversation(c: Conversation) {
    setActiveId(c.id);
    setSheetOpen(false);
    if (models.some((m) => m.id === c.model)) setModel(c.model);
    try {
      const r = await fetch(`/api/conversations/${c.id}`);
      const d = await r.json();
      setMessages(
        (d?.messages ?? []).map((m: Msg) => ({ role: m.role, content: m.content })),
      );
    } catch {
      toast.error("Chargement de la conversation impossible");
    }
  }

  async function removeConversation(id: string) {
    try {
      await fetch(`/api/conversations/${id}`, { method: "DELETE" });
      if (activeId === id) newConversation();
      refreshConversations();
    } catch {
      toast.error("Suppression impossible");
    }
  }

  function pushAssistant(content: string) {
    setMessages((m) => [...m, { role: "assistant", content }]);
  }

  // Action pipeline déclenchée depuis le chat : appelle l'API projet et affiche
  // le résultat comme message local (non persisté dans la conversation LLM).
  async function pipelineAction(
    call: () => Promise<Response>,
    okMsg: (d: Record<string, unknown>) => string,
  ) {
    if (loading) return;
    setLoading(true);
    try {
      const r = await call();
      const d = (await r.json().catch(() => ({}))) as Record<string, unknown>;
      if (!r.ok) throw new Error((d.error as string) ?? "action impossible");
      pushAssistant(okMsg(d));
      onPipelineAction?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "action impossible");
    } finally {
      setLoading(false);
    }
  }

  function launchDevelopment(prompt: string) {
    return pipelineAction(
      () =>
        fetch(`/api/projects/${encodeURIComponent(project!)}/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt, dev_model: "sonnet" }),
        }),
      (d) =>
        `🚀 Développement lancé (${String(
          d.pipeline_id ?? "en cours",
        )}). Je démarre l'analyse — tu seras sollicité aux jalons.`,
    );
  }

  function decide(decision: string, msg: string) {
    return pipelineAction(
      () =>
        fetch(`/api/projects/${encodeURIComponent(project!)}/resume`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision }),
        }),
      () => msg,
    );
  }

  function collect() {
    return pipelineAction(
      () =>
        fetch(`/api/projects/${encodeURIComponent(project!)}/collect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        }),
      () => "📥 Résultat intégré dans la base du projet.",
    );
  }

  async function send() {
    const text = input.trim();
    if (!text || loading) return;

    // Révision : le message porte le retour de correction pour le jalon courant.
    if (project && revising) {
      setInput("");
      setRevising(false);
      setMessages((m) => [...m, { role: "user", content: text }]);
      await decide(`revise:${text}`, `✏️ Révision demandée : « ${text} »`);
      return;
    }

    // Mode Développer : le message décrit le besoin → lance le pipeline.
    if (project && mode === "develop") {
      if (pipelineActive) {
        toast.error("Un pipeline est déjà en cours sur ce projet.");
        return;
      }
      setInput("");
      setMode("chat");
      setMessages((m) => [...m, { role: "user", content: text }]);
      await launchDevelopment(text);
      return;
    }

    // Mode Discuter : chat LLM classique.
    if (!model) return;
    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model,
          messages: next,
          conversationId: activeId,
          project,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error ?? "erreur");
      setMessages((m) => [...m, { role: "assistant", content: data.reply }]);
      if (data.conversationId && data.conversationId !== activeId) {
        setActiveId(data.conversationId);
      }
      refreshConversations();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Échec de la requête");
      setMessages((m) => m.slice(0, -1));
      setInput(text);
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  const list = (
    <ConversationList
      conversations={conversations}
      activeId={activeId}
      onNew={newConversation}
      onSelect={openConversation}
      onDelete={removeConversation}
    />
  );

  return (
    <div className="flex h-[calc(100dvh-9rem)] gap-4">
      {/* Rail conversations — desktop */}
      <aside className="hidden w-64 shrink-0 md:block">{list}</aside>

      {/* Conversation active — largeur plafonnée, alignée au rail */}
      <div className="flex min-w-0 w-full max-w-3xl flex-1 flex-col gap-4">
        <div className="flex items-center gap-2">
          {/* Déclencheur conversations — mobile */}
          <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
            <SheetTrigger className="inline-flex size-9 items-center justify-center rounded-md border hover:bg-accent md:hidden">
              <MessagesSquare className="size-4" />
              <span className="sr-only">Conversations</span>
            </SheetTrigger>
            <SheetContent side="left" className="w-72 p-3">
              <SheetHeader className="p-1">
                <SheetTitle>Conversations</SheetTitle>
              </SheetHeader>
              {list}
            </SheetContent>
          </Sheet>

          <Select
            value={model}
            onValueChange={(v) => {
              if (v) setModel(v);
            }}
            disabled={models.length === 0}
          >
            <SelectTrigger className="w-52">
              <SelectValue
                placeholder={
                  models.length === 0 ? "Aucun modèle disponible" : "Modèle"
                }
              />
            </SelectTrigger>
            <SelectContent>
              {models.map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto rounded-lg border bg-card p-4">
          {messages.length === 0 ? (
            <p className="pt-10 text-center text-sm text-muted-foreground">
              Démarrez la conversation — Claude (forfait) ou un modèle local.
            </p>
          ) : (
            messages.map((m, i) => (
              <div
                key={i}
                className={cn(
                  "flex",
                  m.role === "user" ? "justify-end" : "justify-start",
                )}
              >
                <div
                  className={cn(
                    "max-w-[80%] rounded-lg px-3 py-2 text-sm",
                    m.role === "user"
                      ? "whitespace-pre-wrap bg-primary text-primary-foreground"
                      : "bg-muted",
                  )}
                >
                  {m.role === "user" ? (
                    m.content
                  ) : (
                    <Markdown>{m.content}</Markdown>
                  )}
                </div>
              </div>
            ))
          )}
          {loading ? (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Réflexion…
              </div>
            </div>
          ) : null}
          <div ref={bottomRef} />
        </div>

        {/* Barre d'action + étiquette de mode — chat projet uniquement */}
        {project ? (
          <div className="flex flex-wrap items-center gap-2">
            {status === "awaiting_approval" ? (
              <>
                <span className="text-xs text-muted-foreground">
                  Jalon « {pipeline?.phase} » :
                </span>
                <Button
                  size="sm"
                  disabled={loading}
                  onClick={() =>
                    decide("approve", "✅ Jalon approuvé — je poursuis.")
                  }
                >
                  <Check className="size-4" /> Approuver
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={loading}
                  onClick={() => setRevising(true)}
                >
                  <Pencil className="size-4" /> Réviser
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={loading}
                  onClick={() => decide("stop", "⏹ Pipeline arrêté.")}
                >
                  <Square className="size-4" /> Arrêter
                </Button>
              </>
            ) : null}
            {status === "done" ? (
              <Button size="sm" disabled={loading} onClick={collect}>
                <Download className="size-4" /> Intégrer le résultat
              </Button>
            ) : null}

            {revising ? (
              <div className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
                Mode révision
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setRevising(false)}
                >
                  Annuler
                </Button>
              </div>
            ) : (
              <div className="ml-auto flex items-center gap-1 text-sm">
                <span className="text-muted-foreground">Mode :</span>
                <Button
                  type="button"
                  size="sm"
                  variant={mode === "chat" ? "default" : "outline"}
                  onClick={() => setMode("chat")}
                >
                  <MessagesSquare className="size-4" /> Discuter
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={mode === "develop" ? "default" : "outline"}
                  disabled={pipelineActive}
                  onClick={() => setMode("develop")}
                  title={
                    pipelineActive
                      ? "Un pipeline est déjà en cours"
                      : undefined
                  }
                >
                  <Rocket className="size-4" /> Développer
                </Button>
              </div>
            )}
          </div>
        ) : null}

        <div className="flex items-end gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={
              revising
                ? "Qu'est-ce qui doit être corrigé ?"
                : project && mode === "develop"
                  ? "Décris ce que tu veux développer…"
                  : "Votre message… (Entrée pour envoyer, Maj+Entrée pour un saut de ligne)"
            }
            className="min-h-[3rem] resize-none"
            disabled={loading}
          />
          <MicButton
            disabled={loading}
            onTranscript={(t) =>
              setInput((prev) => (prev ? `${prev} ${t}` : t))
            }
          />
          <Button
            onClick={send}
            disabled={
              loading ||
              !input.trim() ||
              (!revising && mode === "develop" && pipelineActive) ||
              (!revising && mode === "chat" && !model)
            }
            size="icon"
          >
            {revising ? (
              <Check className="size-4" />
            ) : project && mode === "develop" ? (
              <Rocket className="size-4" />
            ) : (
              <Send className="size-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
