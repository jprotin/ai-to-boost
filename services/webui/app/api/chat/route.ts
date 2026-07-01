import { NextResponse } from "next/server";
import { auth } from "@/auth";
import {
  getProjectArtifact,
  getProjectBoard,
  getProjectHistory,
} from "@/lib/api";
import { ragSearch } from "@/lib/rag";
import { resolveModelVersions } from "@/lib/model-versions";
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

// Budgets de contexte (caractères) — évite de saturer les modèles locaux (32k).
const ARTIFACT_PER = 1600;
const ARTIFACT_CAP = 7000;

// Préambule système au périmètre complet du projet (chat dédié projet) : board +
// agents/phases + contenu des artefacts + archives + RAG projet-first. Chaque
// section dégrade en douceur (une source absente n'empêche pas les autres).
async function projectContext(project: string, query: string): Promise<string> {
  const sections: string[] = [];

  let board: Awaited<ReturnType<typeof getProjectBoard>> = null;
  try {
    board = await getProjectBoard(project);
  } catch {
    /* board indisponible → on continue */
  }

  // 1. Board (epics/stories) + entête.
  if (board) {
    const lines = board.epics.map(
      (e) =>
        `- Epic ${e.n} « ${e.title} » [${e.status}] : ` +
        e.stories.map((s) => `${s.title} [${s.status}]`).join(", "),
    );
    sections.push(
      `Tu assistes sur le projet « ${project} » (pipeline : ${board.pipeline?.status ?? "—"}` +
        `${board.pipeline?.phase ? " / " + board.pipeline.phase : ""}).\n` +
        (lines.length
          ? `Epics & stories :\n${lines.join("\n")}`
          : "Pas encore de board."),
    );

    // 2. Agents / phases du pipeline (persona → modèle alias).
    if (board.phases?.length) {
      sections.push(
        "Agents du pipeline (phase → persona → modèle) :\n" +
          board.phases
            .map((p) => `- ${p.key} — ${p.persona} → ${p.model}`)
            .join("\n"),
      );

      // 2b. Versions exactes des alias effectivement utilisés (local via LiteLLM,
      //     Claude via libellés — voir lib/model-versions).
      const versions = await resolveModelVersions(
        board.phases.map((p) => p.model),
      );
      const lines = Object.entries(versions).map(
        ([alias, version]) => `- ${alias} = ${version}`,
      );
      if (lines.length) {
        sections.push(
          "Versions exactes des modèles :\n" + lines.join("\n"),
        );
      }
    }
  }

  // 3. Contenu des artefacts du run courant (tronqué, sous budget global).
  const artifacts = board?.pipeline?.artifacts ?? [];
  if (artifacts.length) {
    const contents = await Promise.all(
      artifacts.map((a) =>
        getProjectArtifact(project, a.key).then((c) => ({
          title: a.title,
          content: c,
        })),
      ),
    );
    let used = 0;
    const parts: string[] = [];
    for (const { title, content } of contents) {
      const c = content.trim();
      if (!c || used >= ARTIFACT_CAP) continue;
      const slice = c.slice(0, ARTIFACT_PER);
      used += slice.length;
      parts.push(
        `### ${title}\n${slice}${c.length > slice.length ? "\n…(tronqué)" : ""}`,
      );
    }
    if (parts.length) {
      sections.push(
        "Contenu des artefacts du projet :\n" + parts.join("\n\n"),
      );
    }
  }

  // 4. Archives (runs passés) — liste courte.
  const runs = await getProjectHistory(project);
  if (runs.length) {
    sections.push(
      "Historique des pipelines (archives) :\n" +
        runs
          .slice(0, 10)
          .map(
            (r) =>
              `- ${r.created ?? "?"} [${r.status ?? "?"}] ${r.prompt ?? "(sans description)"}`,
          )
          .join("\n"),
    );
  }

  // 5. RAG — projet d'abord ; le commun est labellisé « transverse » car il peut
  //    concerner d'autres projets (évite la pollution constatée).
  const hits = await ragSearch(project, query, 5);
  if (hits.length) {
    const projColl = `proj-${project.toLowerCase().replace(/[^a-z0-9_-]/g, "-")}`;
    const fmt = (label: string, list: typeof hits) =>
      list.length
        ? `${label} :\n` +
          list
            .map((h) => `[${h.source}]\n${h.text.slice(0, 600).trim()}`)
            .join("\n\n")
        : "";
    const proj = fmt(
      "Extraits RAG du projet",
      hits.filter((h) => h.collection === projColl),
    );
    const commun = fmt(
      "Extraits RAG transverses (peuvent ne PAS concerner ce projet)",
      hits.filter((h) => h.collection !== projColl),
    );
    sections.push(
      [
        "Documentation indexée (RAG). Appuie-toi en priorité sur les extraits du projet ; cite la source [fichier].",
        proj,
        commun,
      ]
        .filter(Boolean)
        .join("\n\n"),
    );
  }

  return sections.join("\n\n").trim();
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
  const system = project
    ? await projectContext(project, lastUser.content)
    : "";

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
