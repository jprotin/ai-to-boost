import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { AGENT_TOKEN, BACKEND } from "@/lib/backend";

export const runtime = "nodejs";

// Intègre la branche pipeline du projet dans sa base (merge --no-ff côté worker).
export async function POST(
  req: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  const { name } = await params;
  let body: { clean?: boolean };
  try {
    body = await req.json().catch(() => ({}));
  } catch {
    body = {};
  }
  const r = await fetch(
    `${BACKEND.worker}/projects/${encodeURIComponent(name)}/collect`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${AGENT_TOKEN}`,
      },
      body: JSON.stringify({ clean: Boolean(body.clean) }),
    },
  );
  const data = await r.json().catch(() => ({}));
  return NextResponse.json(data, { status: r.ok ? 200 : r.status || 502 });
}
