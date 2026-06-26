import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { BACKEND, BRIDGE_TOKEN, LITELLM_KEY } from "@/lib/backend";
import { CHAT_MODELS } from "@/lib/models";

// Runtime Node (accès host.docker.internal + secrets serveur).
export const runtime = "nodejs";

type Msg = { role: "user" | "assistant"; content: string };

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }

  let body: { model?: string; messages?: Msg[] };
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
  if (messages.length === 0) {
    return NextResponse.json({ error: "messages vides" }, { status: 400 });
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 120_000);
  try {
    if (model.kind === "claude") {
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
        signal: ctrl.signal,
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        return NextResponse.json(
          { error: data?.error ?? "erreur bridge" },
          { status: 502 },
        );
      }
      return NextResponse.json({ reply: String(data.result ?? "").trim() });
    }

    // LiteLLM (OpenAI-compatible) — multi-tour natif. max_tokens élevé : les modèles
    // locaux raisonnent (un budget trop bas renvoie un contenu vide).
    const r = await fetch(`${BACKEND.litellm}/v1/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${LITELLM_KEY}`,
      },
      body: JSON.stringify({
        model: model.id,
        messages,
        max_tokens: 2048,
        temperature: 0.5,
      }),
      signal: ctrl.signal,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      return NextResponse.json(
        { error: data?.error?.message ?? "erreur LiteLLM" },
        { status: 502 },
      );
    }
    const reply = String(data?.choices?.[0]?.message?.content ?? "").trim();
    return NextResponse.json({ reply: reply || "(réponse vide)" });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "erreur";
    return NextResponse.json({ error: msg }, { status: 502 });
  } finally {
    clearTimeout(timer);
  }
}
