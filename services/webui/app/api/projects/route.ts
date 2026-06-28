import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { AGENT_TOKEN, BACKEND } from "@/lib/backend";

export const runtime = "nodejs";

// Crée + enregistre un projet pilotable (worker : git + develop + marqueur .ai-to-boost).
export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  let body: { name?: string; path?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "JSON invalide" }, { status: 400 });
  }
  const name = (body.name ?? "").trim();
  if (!name) {
    return NextResponse.json({ error: "nom requis" }, { status: 400 });
  }
  const r = await fetch(`${BACKEND.worker}/projects`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${AGENT_TOKEN}`,
    },
    body: JSON.stringify({ name, path: body.path?.trim() || undefined }),
  });
  const data = await r.json().catch(() => ({}));
  return NextResponse.json(data, { status: r.ok ? 201 : r.status || 502 });
}
