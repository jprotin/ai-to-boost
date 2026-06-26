// Modèles de chat — données partagées client/serveur (PAS de secret ici).
// Claude passe par le bridge claude -p (forfait, CGU) ; gemma/qwen par LiteLLM.
// `match` = sous-chaîne du nom de modèle sous-jacent côté LiteLLM/LM Studio (pour
// déterminer la disponibilité via /health).
export const CHAT_MODELS = [
  { id: "claude", label: "Claude (forfait)", kind: "claude" as const, match: "" },
  {
    id: "local-gemma",
    label: "Gemma (local)",
    kind: "litellm" as const,
    match: "gemma",
  },
  {
    id: "local-qwen",
    label: "Qwen (local)",
    kind: "litellm" as const,
    match: "qwen",
  },
];

export type ChatModel = (typeof CHAT_MODELS)[number];
export type ChatModelId = ChatModel["id"];

// Libellé court d'un modèle (identifiant worker/LiteLLM → affichage).
export function modelLabel(id: string): string {
  if (id === "claude") return "Claude";
  if (id === "local-gemma") return "Gemma";
  if (id === "local-qwen") return "Qwen";
  return id;
}
