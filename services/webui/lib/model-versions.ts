/**
 * Résolution alias de modèle → version exacte, pour le contexte du chat projet.
 *
 * - Modèles LOCAUX (local-gemma, local-qwen, local-embed) : résolus EN DIRECT via
 *   LiteLLM /model/info (source de vérité, config), avec cache TTL. Renvoie l'ID
 *   Ollama sous-jacent (ex. gemma4:e4b) sans le préfixe fournisseur.
 * - Modèles CLAUDE (claude, opus, sonnet) : libellés statiques — la version exacte
 *   du build est résolue par le CLI `claude -p` à l'exécution, pas dans la config.
 */
import "server-only";
import { BACKEND, LITELLM_KEY } from "@/lib/backend";

// Le curseur dev/doc résout claude → opus (AGENT_MODEL) pour l'architecte et
// selon le curseur (sonnet par défaut) pour dev/doc. Voir claude_agent.py.
// Alias résolus par le CLI `claude -p` (2.1.x) : sonnet → claude-sonnet-5,
// opus → dernier build Opus. Libellés indicatifs (le build exact est côté CLI).
const CLAUDE_LABELS: Record<string, string> = {
  claude:
    "Claude (forfait) — architecte : Opus ; dev/doc : selon le curseur (Sonnet 5 par défaut) ; escalade : Opus",
  opus: "Claude Opus (forfait)",
  sonnet: "Claude Sonnet 5 (forfait)",
};

type Cache = { at: number; map: Record<string, string> };
let cache: Cache | null = null;
const TTL_MS = 60_000;

// Interroge LiteLLM /model/info et construit alias → modèle réel (préfixe retiré).
async function litellmModels(now: number): Promise<Record<string, string>> {
  if (cache && now - cache.at < TTL_MS) return cache.map;
  const map: Record<string, string> = {};
  try {
    const r = await fetch(`${BACKEND.litellm}/model/info`, {
      headers: { Authorization: `Bearer ${LITELLM_KEY}` },
      signal: AbortSignal.timeout(6000),
    });
    if (r.ok) {
      const d = (await r.json().catch(() => ({}))) as {
        data?: { model_name?: string; litellm_params?: { model?: string } }[];
      };
      for (const m of d.data ?? []) {
        const alias = m.model_name;
        const real = m.litellm_params?.model;
        if (alias && real) map[alias] = real.replace(/^[^/]+\//, "");
      }
    }
  } catch {
    /* LiteLLM injoignable → map vide, dégradation sur l'alias */
  }
  cache = { at: now, map };
  return map;
}

// Résout un ensemble d'alias → version exacte (ou l'alias si non résolu).
export async function resolveModelVersions(
  aliases: string[],
): Promise<Record<string, string>> {
  const now = Date.now();
  const unique = Array.from(new Set(aliases));
  const needsLocal = unique.some((a) => !CLAUDE_LABELS[a]);
  const local = needsLocal ? await litellmModels(now) : {};
  const out: Record<string, string> = {};
  for (const a of unique) {
    out[a] = CLAUDE_LABELS[a] ?? local[a] ?? a;
  }
  return out;
}
