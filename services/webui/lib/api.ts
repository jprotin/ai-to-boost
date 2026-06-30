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

export type Tokens = { input: number; output: number };
export type Story = {
  id: string;
  title: string;
  status: string;
  detail?: string;
  tokens?: Tokens | null;
};
export type Epic = {
  n: number;
  title: string;
  status: string;
  stories: Story[];
  tokens?: Tokens | null;
};
export type Phase = { key: string; persona: string; model: string };
export type Artifact = { key: string; title: string };
export type Board = {
  name: string;
  pipeline: {
    id?: string;
    status?: string;
    phase?: string;
    branch?: string;
    prompt?: string;
    awaiting?: string;
    artifacts?: Artifact[];
    tokens?: Tokens | null;
    acceptance?: { ok: boolean; reason?: string; tests?: string } | null;
  };
  epics: Epic[];
  phases?: Phase[];
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

// Board d'un projet (epics/stories + pipeline). null si projet inconnu (404).
export async function getProjectBoard(name: string): Promise<Board | null> {
  const r = await fetch(
    `${BACKEND.worker}/projects/${encodeURIComponent(name)}/board`,
    { headers: { Authorization: `Bearer ${AGENT_TOKEN}` }, cache: "no-store" },
  );
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`worker board: HTTP ${r.status}`);
  return r.json();
}
