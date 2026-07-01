import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { BACKEND, WHISPER_MODEL } from "@/lib/backend";

export const runtime = "nodejs";

// Taille max d'un extrait audio dicté (garde-fou : ~1 min d'opus mono ≈ 1 Mo).
const MAX_AUDIO_BYTES = 10 * 1024 * 1024;

// Proxy STT : reçoit un blob audio du micro navigateur et le relaie à whisper
// (speaches, API compatible OpenAI). Whisper est un service local sans auth ;
// l'accès reste protégé par la session webui.
export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "non authentifié" }, { status: 401 });
  }

  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return NextResponse.json({ error: "audio manquant" }, { status: 400 });
  }
  const audio = form.get("audio");
  if (!(audio instanceof Blob) || audio.size === 0) {
    return NextResponse.json({ error: "audio manquant" }, { status: 400 });
  }
  if (audio.size > MAX_AUDIO_BYTES) {
    return NextResponse.json({ error: "extrait trop long" }, { status: 413 });
  }

  // Champs conformes à l'API OpenAI /v1/audio/transcriptions (speaches).
  const upstream = new FormData();
  upstream.set("file", audio, "audio.webm");
  upstream.set("model", WHISPER_MODEL);
  upstream.set("language", "fr");
  upstream.set("response_format", "json");

  let r: Response;
  try {
    r = await fetch(`${BACKEND.whisper}/v1/audio/transcriptions`, {
      method: "POST",
      body: upstream,
    });
  } catch {
    return NextResponse.json(
      { error: "service de transcription injoignable" },
      { status: 502 },
    );
  }

  if (!r.ok) {
    return NextResponse.json(
      { error: "échec de la transcription" },
      { status: r.status || 502 },
    );
  }
  const data = (await r.json().catch(() => ({}))) as { text?: string };
  return NextResponse.json({ text: (data.text ?? "").trim() });
}
