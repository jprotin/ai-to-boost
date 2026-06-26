import { NextResponse } from "next/server";
import { auth } from "@/auth";
import {
  addMessage,
  conversationExists,
  createConversation,
} from "@/lib/db/queries";
import { BACKEND, BRIDGE_TOKEN, LITELLM_KEY } from "@/lib/backend";
import { CHAT_MODELS } from "@/lib/models";

// Runtime Node (accès host.docker.internal + secrets serveur + SQLite).
export const runtime = "nodejs";

type Msg = { role: "user" | "assistant"; content: string };

async function generate(
  kind: "claude" | "litellm",
  modelId: string,
  messages: Msg[],
  signal: AbortSignal,
): Promise<{ reply?: string; error?: string }> {
  if (kind === "claude") {
    // claude -p (forfait, CGU) prend un prompt unique → on sérialise l'historique.
    const prompt =
      messages
        .map(
          (m) =>
            `${m.role === "user" ? "Utilisateur" : "Assistant"}: ${m.content}`,
        )
        .join("\n\n") + "\n\nAssistant:";
    const r = await fetch(`${BACKEND.bridge}/run`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${BRIDGE_TOKEN}`,
      },
      body: JSON.stringify({ prompt }),
      signal,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return { error: data?.error ?? "erreur bridge" };
    return { reply: String(data.result ?? "").trim() };
  }
  // LiteLLM (OpenAI-compatible), multi-tour natif. max_tokens élevé (modèles à raisonnement).
  const r = await fetch(`${BACKEND.litellm}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${LITELLM_KEY}`,
    },
    body: JSON.stringify({
      model: modelId,
      messages,
      max_tokens: 2048,
      temperature: 0.5,
    }),
    signal,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) return { error: data?.error?.message ?? "erreur LiteLLM" };
  return { reply: String(data?.choices?.[0]?.message?.content ?? "").trim() };
}

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }

  let body: { model?: string; messages?: Msg[]; conversationId?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "JSON invalide" }, { status: 400 });
  }

  const messages = Array.isArray(body.messages) ? body.messages : [];
  const model = CHAT_MODELS.find((m) => m.id === (body.model ?? ""));
  if (!model) {
    return NextResponse.json({ error: "modèle inconnu" }, { status: 400 });
  }
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  if (!lastUser) {
    return NextResponse.json({ error: "aucun message utilisateur" }, { status: 400 });
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 120_000);
  let out: { reply?: string; error?: string };
  try {
    out = await generate(model.kind, model.id, messages, ctrl.signal);
  } catch (e) {
    out = { error: e instanceof Error ? e.message : "erreur" };
  } finally {
    clearTimeout(timer);
  }
  if (out.error || out.reply === undefined) {
    return NextResponse.json({ error: out.error ?? "erreur" }, { status: 502 });
  }
  const reply = out.reply || "(réponse vide)";

  // Persistance : crée la conversation au 1er message, puis enregistre l'échange.
  let conversationId = body.conversationId;
  if (!conversationId || !conversationExists(conversationId)) {
    conversationId = createConversation(model.id, lastUser.content);
  }
  addMessage(conversationId, "user", lastUser.content);
  addMessage(conversationId, "assistant", reply);

  return NextResponse.json({ reply, conversationId });
}
