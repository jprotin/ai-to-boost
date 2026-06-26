import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { AGENT_TOKEN, BACKEND } from "@/lib/backend";

export const runtime = "nodejs";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  const { name } = await params;
  let body: { decision?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "JSON invalide" }, { status: 400 });
  }
  const decision = (body.decision ?? "").trim();
  if (!decision) {
    return NextResponse.json({ error: "décision requise" }, { status: 400 });
  }
  const r = await fetch(
    `${BACKEND.worker}/projects/${encodeURIComponent(name)}/resume`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${AGENT_TOKEN}`,
      },
      body: JSON.stringify({ decision }),
    },
  );
  const data = await r.json().catch(() => ({}));
  return NextResponse.json(data, { status: r.ok ? 202 : r.status || 502 });
}
