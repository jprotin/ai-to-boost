import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getHealth } from "@/lib/health";

export const runtime = "nodejs";

// Santé des backends (probes readiness), consommée côté client par la page
// Settings — hors du chemin de rendu SSR pour ne jamais figer la page.
export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  return NextResponse.json(await getHealth());
}
