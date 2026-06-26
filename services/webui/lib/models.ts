// Modèles de chat — données partagées client/serveur (PAS de secret ici).
// Claude passe par le bridge claude -p (forfait, CGU) ; gemma/qwen par LiteLLM.
export const CHAT_MODELS = [
  { id: "claude", label: "Claude (forfait)", kind: "claude" as const },
  { id: "local-gemma", label: "Gemma (local)", kind: "litellm" as const },
  { id: "local-qwen", label: "Qwen (local)", kind: "litellm" as const },
];

export type ChatModelId = (typeof CHAT_MODELS)[number]["id"];
