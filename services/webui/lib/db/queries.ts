import "server-only";
import { desc, eq } from "drizzle-orm";
import { db, schema } from "./index";

const { conversations, messages } = schema;

export function listConversations() {
  return db
    .select()
    .from(conversations)
    .orderBy(desc(conversations.updatedAt))
    .all();
}

export function getMessages(conversationId: string) {
  return db
    .select()
    .from(messages)
    .where(eq(messages.conversationId, conversationId))
    .orderBy(messages.createdAt)
    .all();
}

export function conversationExists(id: string) {
  return Boolean(
    db
      .select({ id: conversations.id })
      .from(conversations)
      .where(eq(conversations.id, id))
      .get(),
  );
}

export function createConversation(model: string, title: string) {
  const now = Date.now();
  const id = crypto.randomUUID();
  db.insert(conversations)
    .values({
      id,
      title: title.slice(0, 80) || "Conversation",
      model,
      createdAt: now,
      updatedAt: now,
    })
    .run();
  return id;
}

export function addMessage(
  conversationId: string,
  role: "user" | "assistant",
  content: string,
) {
  const now = Date.now();
  db.insert(messages)
    .values({ id: crypto.randomUUID(), conversationId, role, content, createdAt: now })
    .run();
  db.update(conversations)
    .set({ updatedAt: now })
    .where(eq(conversations.id, conversationId))
    .run();
}

export function deleteConversation(id: string) {
  db.delete(messages).where(eq(messages.conversationId, id)).run();
  db.delete(conversations).where(eq(conversations.id, id)).run();
}
