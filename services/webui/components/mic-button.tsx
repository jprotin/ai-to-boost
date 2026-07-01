"use client";

import { Loader2, Mic, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type State = "idle" | "recording" | "transcribing";

// Bouton micro réutilisable : enregistre la voix (MediaRecorder), l'envoie au
// proxy /api/transcribe (whisper) et remonte le texte via onTranscript.
// getUserMedia exige un contexte sécurisé — OK sur http://127.0.0.1 (localhost),
// bloqué via une IP LAN en http (message explicite dans ce cas).
export function MicButton({
  onTranscript,
  disabled,
}: {
  onTranscript: (text: string) => void;
  disabled?: boolean;
}) {
  const [state, setState] = useState<State>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const stopTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  // Coupe le micro si le composant est démonté en cours d'enregistrement.
  useEffect(() => stopTracks, [stopTracks]);

  async function transcribe(blob: Blob) {
    setState("transcribing");
    try {
      const fd = new FormData();
      fd.set("audio", blob, "audio.webm");
      const r = await fetch("/api/transcribe", { method: "POST", body: fd });
      const d = (await r.json().catch(() => ({}))) as {
        text?: string;
        error?: string;
      };
      if (!r.ok) throw new Error(d.error ?? "échec de la transcription");
      const text = (d.text ?? "").trim();
      if (text) onTranscript(text);
      else toast.info("Rien n'a été transcrit.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "échec de la transcription");
    } finally {
      setState("idle");
    }
  }

  async function start() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      toast.error("Micro indisponible (contexte non sécurisé ?).");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      toast.error("Accès au micro refusé.");
      return;
    }
    streamRef.current = stream;
    chunksRef.current = [];
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    rec.onstop = () => {
      stopTracks();
      const blob = new Blob(chunksRef.current, {
        type: rec.mimeType || "audio/webm",
      });
      if (blob.size > 0) void transcribe(blob);
      else setState("idle");
    };
    recorderRef.current = rec;
    rec.start();
    setState("recording");
  }

  function stop() {
    recorderRef.current?.stop();
    recorderRef.current = null;
  }

  const busy = state === "transcribing";

  return (
    <Button
      type="button"
      size="icon"
      variant={state === "recording" ? "destructive" : "outline"}
      disabled={disabled || busy}
      onClick={state === "recording" ? stop : start}
      aria-label={
        state === "recording" ? "Arrêter la dictée" : "Dicter au micro"
      }
      title={state === "recording" ? "Arrêter la dictée" : "Dicter au micro"}
    >
      {state === "transcribing" ? (
        <Loader2 className="size-4 animate-spin" />
      ) : state === "recording" ? (
        <Square className="size-4" />
      ) : (
        <Mic className={cn("size-4")} />
      )}
    </Button>
  );
}
