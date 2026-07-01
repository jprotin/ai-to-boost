import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { CHAT_MODELS } from "@/lib/models";

export const runtime = "nodejs";

// Liste statique (aucun sondage réseau) → peuplage instantané du sélecteur. La
// disponibilité live des backends est surfacée séparément (Settings /api/health).
export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  const models = CHAT_MODELS.map((m) => ({ id: m.id, label: m.label }));
  return NextResponse.json({ models });
}
