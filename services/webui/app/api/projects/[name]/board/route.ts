import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getProjectBoard } from "@/lib/api";

export const runtime = "nodejs";

// Board d'un projet pour le rafraîchissement live côté client (polling, C3.5).
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  const { name } = await params;
  try {
    const board = await getProjectBoard(name);
    if (board === null) {
      return NextResponse.json({ error: "projet inconnu" }, { status: 404 });
    }
    return NextResponse.json(board);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "erreur" },
      { status: 502 },
    );
  }
}
