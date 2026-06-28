import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getProjectBoard } from "@/lib/api";
import {
  addMessage,
  conversationExists,
  createConversation,
} from "@/lib/db/queries";
import { BACKEND, BRIDGE_TOKEN, LITELLM_KEY } from "@/lib/backend";
import { CHAT_MODELS } from "@/lib/models";

export const runtime = "nodejs";

type Msg = { role: "user" | "assistant"; content: string };

async function generate(
  kind: "claude" | "litellm",
  modelId: string,
  messages: Msg[],
  system: string,
  signal: AbortSignal,
): Promise<{ reply?: string; error?: string }> {
  if (kind === "claude") {
    const prompt =
      (system ? `${system}\n\n` : "") +
      messages
        .map(
          (m) =>
            `${m.role === "user" ? "Utilisateur" : "Assistant"}: ${m.content}`,
        )
        .join("\n\n") +
      "\n\nAssistant:";
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
  const payload = system
    ? [{ role: "system", content: system }, ...messages]
    : messages;
  const r = await fetch(`${BACKEND.litellm}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${LITELLM_KEY}`,
    },
    body: JSON.stringify({
      model: modelId,
      messages: payload,
      // Budget large : local-qwen (qwen3.5:9b) est un reasoner bavard — via /v1 la
      // réflexion est comptée dans max_tokens puis retirée du content ; un budget
      // trop bas renvoie une réponse vide (cf. ADR 0007, claude_agent._llm_local).
      max_tokens: 16000,
      temperature: 0.5,
    }),
    signal,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) return { error: data?.error?.message ?? "erreur LiteLLM" };
  return { reply: String(data?.choices?.[0]?.message?.content ?? "").trim() };
}

// Préambule système décrivant l'état du projet (chat dédié projet, C3.4).
async function projectContext(project: string): Promise<string> {
  try {
    const b = await getProjectBoard(project);
    if (!b) return "";
    const lines = b.epics.map(
      (e) =>
        `- Epic ${e.n} « ${e.title} » [${e.status}] : ` +
        e.stories.map((s) => `${s.title} [${s.status}]`).join(", "),
    );
    return (
      `Tu assistes sur le projet « ${project} » (pipeline : ${b.pipeline?.status ?? "—"}` +
      `${b.pipeline?.phase ? " / " + b.pipeline.phase : ""}).\n` +
      (lines.length ? `Epics & stories :\n${lines.join("\n")}` : "Pas encore de board.")
    );
  } catch {
    return "";
  }
}

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }

  let body: {
    model?: string;
    messages?: Msg[];
    conversationId?: string;
    project?: string;
  };
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

  const project = body.project ?? null;
  const system = project ? await projectContext(project) : "";

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 120_000);
  let out: { reply?: string; error?: string };
  try {
    out = await generate(model.kind, model.id, messages, system, ctrl.signal);
  } catch (e) {
    out = { error: e instanceof Error ? e.message : "erreur" };
  } finally {
    clearTimeout(timer);
  }
  if (out.error || out.reply === undefined) {
    return NextResponse.json({ error: out.error ?? "erreur" }, { status: 502 });
  }
  const reply = out.reply || "(réponse vide)";

  let conversationId = body.conversationId;
  if (!conversationId || !conversationExists(conversationId)) {
    conversationId = createConversation(model.id, lastUser.content, project);
  }
  addMessage(conversationId, "user", lastUser.content);
  addMessage(conversationId, "assistant", reply);

  return NextResponse.json({ reply, conversationId });
}
