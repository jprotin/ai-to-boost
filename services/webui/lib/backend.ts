/**
 * URLs du backend existant — utilisées UNIQUEMENT côté serveur (BFF, ADR 0005).
 * Le secret AGENT_TOKEN ne doit jamais être exposé au navigateur : il n'est lu que
 * dans des modules serveur (route handlers / server actions / server components).
 */
import "server-only";

export const BACKEND = {
  // Worker agentique (jobs + pipelines + API lecture à venir).
  worker: process.env.WORKER_URL ?? "http://host.docker.internal:8089",
  // Bridge claude -p (forfait, CGU) pour le chat Claude.
  bridge: process.env.BRIDGE_URL ?? "http://host.docker.internal:8088",
  // LiteLLM (modèles locaux gemma/qwen) pour le chat local.
  litellm: process.env.LITELLM_URL ?? "http://host.docker.internal:4000",
};

export const AGENT_TOKEN = process.env.AGENT_TOKEN ?? "";
// Token Bearer du bridge claude -p et clé maître LiteLLM (chat). Côté serveur uniquement.
export const BRIDGE_TOKEN = process.env.BRIDGE_TOKEN ?? "";
export const LITELLM_KEY = process.env.LITELLM_KEY ?? "";
