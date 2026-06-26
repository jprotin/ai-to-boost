import "server-only";
import { AGENT_TOKEN, BACKEND, BRIDGE_TOKEN, LITELLM_KEY } from "./backend";
import { CHAT_MODELS } from "./models";

async function fetchJson(
  url: string,
  headers: Record<string, string>,
  ms: number,
): Promise<unknown | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(url, { headers, signal: ctrl.signal, cache: "no-store" });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// Santé des backends (BFF, ADR 0005). worker/bridge/health publics ; litellm readiness.
export async function getHealth() {
  const [worker, bridge, litellm] = await Promise.all([
    fetchJson(`${BACKEND.worker}/health`, { Authorization: `Bearer ${AGENT_TOKEN}` }, 5000),
    fetchJson(`${BACKEND.bridge}/health`, { Authorization: `Bearer ${BRIDGE_TOKEN}` }, 5000),
    fetchJson(`${BACKEND.litellm}/health/readiness`, {}, 5000),
  ]);
  return {
    worker: Boolean(worker),
    bridge: Boolean(bridge),
    litellm: Boolean(litellm),
  };
}

// Modèles réellement disponibles (bridge sain + LM Studio chargés via LiteLLM /health).
export async function getAvailableModels(): Promise<{ id: string; label: string }[]> {
  const [bridge, litellm] = await Promise.all([
    fetchJson(`${BACKEND.bridge}/health`, { Authorization: `Bearer ${BRIDGE_TOKEN}` }, 6000),
    fetchJson(`${BACKEND.litellm}/health`, { Authorization: `Bearer ${LITELLM_KEY}` }, 12000),
  ]);
  const claudeOk = (bridge as { status?: string } | null)?.status === "ok";
  const endpoints =
    (litellm as { healthy_endpoints?: { model?: string }[] } | null)
      ?.healthy_endpoints ?? [];
  const healthy = endpoints.map((e) => String(e.model ?? "").toLowerCase());
  return CHAT_MODELS.filter((m) =>
    m.kind === "claude" ? claudeOk : healthy.some((h) => m.match && h.includes(m.match)),
  ).map((m) => ({ id: m.id, label: m.label }));
}
