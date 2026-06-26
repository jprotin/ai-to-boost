"use client";

import { Loader2, MessagesSquare, Send } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  ConversationList,
  type Conversation,
} from "@/components/conversation-list";
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

type Msg = { role: "user" | "assistant"; content: string };
type Model = { id: string; label: string };

export function Chat({ project }: { project?: string }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

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

  async function send() {
    const text = input.trim();
    if (!text || loading || !model) return;
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
                    "max-w-[80%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm",
                    m.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted",
                  )}
                >
                  {m.content}
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

        <div className="flex items-end gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Votre message… (Entrée pour envoyer, Maj+Entrée pour un saut de ligne)"
            className="min-h-[3rem] resize-none"
            disabled={loading}
          />
          <Button
            onClick={send}
            disabled={loading || !input.trim() || !model}
            size="icon"
          >
            <Send className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
