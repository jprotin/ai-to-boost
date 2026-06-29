import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { AGENT_TOKEN, BACKEND } from "@/lib/backend";

export const runtime = "nodejs";

// Contenu d'un artefact (PRD/archi/epics) d'un run archivé.
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ name: string; pid: string; key: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  const { name, pid, key } = await params;
  const r = await fetch(
    `${BACKEND.worker}/projects/${encodeURIComponent(name)}/history/${encodeURIComponent(pid)}/artifact/${encodeURIComponent(key)}`,
    { headers: { Authorization: `Bearer ${AGENT_TOKEN}` }, cache: "no-store" },
  );
  const data = await r.json().catch(() => ({}));
  return NextResponse.json(data, { status: r.ok ? 200 : r.status || 502 });
}
