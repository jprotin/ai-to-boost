/**
 * Requête RAG côté serveur (BFF) : interroge le service `rag` (FastEmbed nomic
 * + Qdrant) sur les deux portées — commune (`knowledge`) et projet (`proj-<slug>`).
 * Dégradation douce : toute erreur/indispo renvoie [] (le chat continue sans RAG).
 */
import "server-only";
import { BACKEND } from "@/lib/backend";

export type RagHit = {
  score: number;
  source: string;
  collection: string;
  text: string;
};

// Même slug que le worker (claude_agent._rag_mcp) : minuscules + [^a-z0-9_-] → '-'.
function projectCollection(project: string): string {
  return `proj-${project.toLowerCase().replace(/[^a-z0-9_-]/g, "-")}`;
}

export async function ragSearch(
  project: string | null,
  query: string,
  limit = 5,
): Promise<RagHit[]> {
  const q = query.trim();
  if (!q) return [];
  const collections = ["knowledge"];
  if (project) collections.push(projectCollection(project));
  try {
    const r = await fetch(`${BACKEND.rag}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ collections, query: q, limit }),
      signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) return [];
    const d = (await r.json().catch(() => ({}))) as { hits?: RagHit[] };
    return Array.isArray(d.hits) ? d.hits : [];
  } catch {
    return [];
  }
}
