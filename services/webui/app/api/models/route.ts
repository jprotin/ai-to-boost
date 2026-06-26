import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getAvailableModels } from "@/lib/health";

export const runtime = "nodejs";

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  return NextResponse.json({ models: await getAvailableModels() });
}
