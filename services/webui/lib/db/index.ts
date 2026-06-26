import "server-only";
import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import * as schema from "./schema";

// Persistance des conversations — SQLite local (ADR 0005), mono-utilisateur. Fichier dans
// un volume docker. Tables créées de façon idempotente (pas de drizzle-kit dans l'image).
function createDb() {
  const dbPath =
    process.env.WEBUI_DB_PATH ?? path.join(process.cwd(), "data", "webui.db");
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const sqlite = new Database(dbPath);
  sqlite.pragma("journal_mode = WAL");
  sqlite.exec(`
    CREATE TABLE IF NOT EXISTS conversations (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      model TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY,
      conversation_id TEXT NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
  `);
  // Migration idempotente : colonne project (chat dédié projet, C3.4) sur une base existante.
  try {
    sqlite.exec("ALTER TABLE conversations ADD COLUMN project TEXT");
  } catch {
    /* colonne déjà présente */
  }
  return drizzle(sqlite, { schema });
}

// Singleton (évite de multiplier les handles en dev hot-reload).
const g = globalThis as unknown as { __webuiDb?: ReturnType<typeof createDb> };
export const db = g.__webuiDb ?? createDb();
if (process.env.NODE_ENV !== "production") g.__webuiDb = db;

export { schema };
