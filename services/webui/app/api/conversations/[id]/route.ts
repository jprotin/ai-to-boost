import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { deleteConversation, getMessages } from "@/lib/db/queries";

export const runtime = "nodejs";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  const { id } = await params;
  return NextResponse.json({ messages: getMessages(id) });
}

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }
  const { id } = await params;
  deleteConversation(id);
  return NextResponse.json({ ok: true });
}
