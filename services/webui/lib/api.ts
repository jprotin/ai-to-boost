import "server-only";
import { AGENT_TOKEN, BACKEND } from "@/lib/backend";

export type Project = {
  name: string;
  path: string;
  base_branch?: string;
  last_pipeline?: string;
  active: boolean;
  exists: boolean;
  pipeline_status?: string;
  pipeline_phase?: string;
};

// Lecture des projets via l'API du worker (source de vérité unique, ADR 0005).
// AGENT_TOKEN reste côté serveur. `cache: no-store` : données toujours fraîches.
export async function getProjects(): Promise<Project[]> {
  const r = await fetch(`${BACKEND.worker}/projects`, {
    headers: { Authorization: `Bearer ${AGENT_TOKEN}` },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`worker /projects: HTTP ${r.status}`);
  const data = await r.json();
  return data?.projects ?? [];
}
