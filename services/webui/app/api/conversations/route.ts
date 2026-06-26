import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { listConversations } from "@/lib/db/queries";

export const runtime = "nodejs";

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  return NextResponse.json({ conversations: listConversations() });
}
