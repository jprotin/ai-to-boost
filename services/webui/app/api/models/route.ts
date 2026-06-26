import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { BACKEND, BRIDGE_TOKEN, LITELLM_KEY } from "@/lib/backend";
import { CHAT_MODELS } from "@/lib/models";

export const runtime = "nodejs";

async function fetchJson(url: string, headers: Record<string, string>, ms: number) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(url, { headers, signal: ctrl.signal });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// Liste des modèles RÉELLEMENT disponibles : bridge claude -p sain + modèles LiteLLM
// dont le backend (LM Studio) est chargé (via /health). Évite de proposer un modèle
// non chargé (ex. qwen absent de LM Studio).
export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }

  const [bridge, litellm] = await Promise.all([
    fetchJson(`${BACKEND.bridge}/health`, { Authorization: `Bearer ${BRIDGE_TOKEN}` }, 6000),
    fetchJson(`${BACKEND.litellm}/health`, { Authorization: `Bearer ${LITELLM_KEY}` }, 12000),
  ]);

  const claudeOk = bridge?.status === "ok";
  const healthy: string[] = Array.isArray(litellm?.healthy_endpoints)
    ? litellm.healthy_endpoints.map((e: { model?: string }) =>
        String(e.model ?? "").toLowerCase(),
      )
    : [];

  const available = CHAT_MODELS.filter((m) => {
    if (m.kind === "claude") return claudeOk;
    return healthy.some((h) => m.match && h.includes(m.match));
  }).map((m) => ({ id: m.id, label: m.label }));

  return NextResponse.json({ models: available });
}
