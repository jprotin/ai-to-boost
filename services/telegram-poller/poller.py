#!/usr/bin/env python3
"""telegram-poller — adaptateur Telegram (local-first, sans exposition internet).

Boucle de long-polling Telegram (getUpdates), filtre par allowlist de chat IDs,
transcrit la voix via whisper, transmet le texte au "cerveau" n8n (webhook local)
et renvoie la réponse dans Telegram. Cf. ADR 0003 et docs/runbooks/phase4-telegram.md.

Le token Telegram ne vit QUE dans ce service. n8n ne voit que {chat_id, text}.

Variables d'environnement (cf. .env) :
  TELEGRAM_BOT_TOKEN          (requis) token @BotFather
  TELEGRAM_ALLOWED_CHAT_IDS   (requis) IDs autorisés, séparés par des virgules
  N8N_WEBHOOK_URL             défaut http://n8n:5678/webhook/telegram-in
  WHISPER_URL                 défaut http://whisper:8000
  WHISPER_MODEL               défaut Systran/faster-whisper-medium
  POLL_TIMEOUT                long-poll Telegram, défaut 30 s
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED = {
    c.strip()
    for c in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if c.strip()
}
N8N_WEBHOOK_URL = os.environ.get(
    "N8N_WEBHOOK_URL", "http://n8n:5678/webhook/telegram-in"
)
WHISPER_URL = os.environ.get("WHISPER_URL", "http://whisper:8000").rstrip("/")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "Systran/faster-whisper-medium")
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "30"))
API = f"https://api.telegram.org/bot{TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{TOKEN}"


def _get(url: str, timeout: int):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else {}


def _download(url: str, timeout: int = 120) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def transcribe(file_bytes: bytes, filename: str, content_type: str) -> str:
    boundary = "----aitoboost" + os.urandom(8).hex()
    parts = []
    for k, v in (
        ("model", WHISPER_MODEL),
        ("language", "fr"),
        ("response_format", "json"),
    ):
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
    )
    body = b"".join(parts) + file_bytes + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{WHISPER_URL}/v1/audio/transcriptions",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read()).get("text", "").strip()


def voice_to_text(file_id: str) -> str:
    info = _get(f"{API}/getFile?file_id={file_id}", timeout=30)
    file_path = info["result"]["file_path"]
    audio = _download(f"{FILE_API}/{file_path}")
    return transcribe(audio, os.path.basename(file_path) or "voice.oga", "audio/ogg")


def send_message(chat_id, text: str) -> None:
    _post_json(f"{API}/sendMessage", {"chat_id": chat_id, "text": text}, timeout=30)


def handle(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg.get("chat", {}).get("id")
    if str(chat_id) not in ALLOWED:
        print(f"[skip] chat_id non autorisé: {chat_id}", flush=True)
        return
    if "text" in msg:
        user_text = msg["text"]
    elif "voice" in msg or "audio" in msg:
        send_message(chat_id, "🎙️ Transcription en cours…")
        media = msg.get("voice") or msg.get("audio")
        user_text = voice_to_text(media["file_id"])
    else:
        send_message(chat_id, "Type de message non supporté (texte ou voix).")
        return
    try:
        resp = _post_json(N8N_WEBHOOK_URL, {"chat_id": chat_id, "text": user_text})
        reply = (
            resp.get("reply") if isinstance(resp, dict) else None
        ) or "(pas de réponse)"
    except Exception as exc:
        reply = f"Erreur traitement: {exc}"
    send_message(chat_id, reply)


def main() -> None:
    if not TOKEN or not ALLOWED:
        sys.exit("TELEGRAM_BOT_TOKEN et TELEGRAM_ALLOWED_CHAT_IDS requis (cf. .env)")
    print(f"telegram-poller démarré (allowlist: {sorted(ALLOWED)})", flush=True)
    offset = 0
    while True:
        try:
            url = f"{API}/getUpdates?timeout={POLL_TIMEOUT}"
            if offset:
                url += f"&offset={offset}"
            data = _get(url, timeout=POLL_TIMEOUT + 10)
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    handle(upd)
                except Exception as exc:
                    print(f"[err] handle: {exc}", flush=True)
        except urllib.error.HTTPError as exc:
            print(f"[err] Telegram HTTP {exc.code} — pause 10s", flush=True)
            time.sleep(10)
        except Exception as exc:
            print(f"[err] poll: {exc} — pause 5s", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
