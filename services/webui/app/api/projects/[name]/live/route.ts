import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { AGENT_TOKEN, BACKEND } from "@/lib/backend";

export const runtime = "nodejs";

// Flux live des actions de l'IA pour le pipeline courant du projet (polling-tail).
// Relaie le curseur `since` vers le worker ; renvoie { pid, events, next }.
export async function GET(
  req: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  const { name } = await params;
  const since = new URL(req.url).searchParams.get("since") ?? "0";
  const r = await fetch(
    `${BACKEND.worker}/projects/${encodeURIComponent(name)}/live?since=${encodeURIComponent(since)}`,
    { headers: { Authorization: `Bearer ${AGENT_TOKEN}` }, cache: "no-store" },
  );
  const data = await r.json().catch(() => ({}));
  return NextResponse.json(data, { status: r.ok ? 200 : r.status || 502 });
}
