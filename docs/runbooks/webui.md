# Runbook — Web UI tour de contrôle (`webui`)

Web-app Next.js (App Router + shadcn/ui) qui pilotera ai-to-boost depuis le navigateur
(ADR 0005). Local-only (`127.0.0.1`), mono-utilisateur, dockerisée. Remplacera `bmad-ui`.

- Code : `services/webui/` · Image : `Dockerfile` (build standalone) · Service compose : `webui`
- Accès : <http://127.0.0.1:3001>
- **État : opérationnel** — auth, chat (Claude bridge / LiteLLM local), Projets (CRUD),
  Projet (board + pipeline + artefacts + archive + tokens), Dashboard, Paramètres.
  Parcours utilisateur : [guide de déploiement](../guide-deploiement.md).

## Architecture (rappel ADR 0005)

- **BFF** (API routes / server components Next) = seul à parler au backend ; le navigateur
  ne voit jamais `AGENT_TOKEN`.
- Cibles : worker `:8089`, bridge `claude -p` `:8088`, LiteLLM `:4000`.
- **Auth** : Auth.js (provider credentials), session JWT. Protection au **niveau du layout**
  (`app/(dash)/layout.tsx` appelle `auth()` + `redirect`) — pas de middleware (déprécié →
  `proxy` en Next 16).

## Configuration (`services/webui/webui.env`, non versionné)

Secrets isolés dans `webui.env` (chargé en `env_file` par compose ; le hash bcrypt contient
des `$` incompatibles avec l'interpolation du `.env` racine). Modèle : `webui.env.example`.

```bash
AUTH_SECRET=$(openssl rand -hex 32)
WEBUI_USER=admin
WEBUI_PASSWORD_HASH=$(cd services/webui && node -e "console.log(require('bcryptjs').hashSync('VOTRE_MDP',10))")
```

> Défaut posé à l'install : `admin` / `ai2b-admin` — **à changer**.

## Lancer

### Via Docker (cible)

```bash
docker compose build webui
docker compose up -d webui
# http://127.0.0.1:3001
```

### En dev local (itération rapide)

Créer `services/webui/.env.local` (non versionné) :

```bash
AUTH_SECRET=<même secret>
WEBUI_USER=admin
WEBUI_PASSWORD_HASH=<hash bcrypt>
WORKER_URL=http://127.0.0.1:8089
BRIDGE_URL=http://127.0.0.1:8088
LITELLM_URL=http://127.0.0.1:4000
```

```bash
cd services/webui
npm install
npm run dev   # http://localhost:3000
```

## Vérifs

- `npm run build` doit passer (type-check + build).
- `/login` accessible sans session ; toute autre page redirige vers `/login` si non connecté.
- Connexion → 5 pages (shells) + menu utilisateur → Déconnexion → retour `/login`.

## Chat (C3.1 / C3.1b)

- **Modèles dynamiques** : `GET /api/models` sonde le bridge (`/health`) et LiteLLM
  (`/health`) → ne propose que les modèles **réellement disponibles** (ex. `local-qwen`
  masqué s'il n'est pas chargé dans Ollama).
- **Persistance** : conversations + messages en **SQLite** (Drizzle), fichier
  `WEBUI_DB_PATH` (défaut `/app/data/webui.db`, volume docker `webui-data`). Tables créées
  de façon idempotente au démarrage (pas de migration à lancer). Mémoire = l'historique est
  rejoué à chaque appel (LiteLLM multi-tour ; Claude via transcript).
- Routes : `POST /api/chat` (génère + persiste), `GET /api/conversations`,
  `GET|DELETE /api/conversations/<id>`.
- **Image** : base `node:24-slim` (et non alpine) pour le binaire natif `better-sqlite3`.

## Projets & pipeline (lots F1–F6)

Le BFF parle au worker `:8089` (`AGENT_TOKEN`, server-only). Pages & routes :

- **Projets** (`app/(dash)/projects`) : liste (`getProjects`), **création** (`POST /api/projects`)
  et **suppression** (`DELETE /api/projects/[name]`, retrait du registre, non destructif).
- **Projet** (`components/project-view.tsx`) : onglets **Board / Artefacts / Archive / Chat**,
  bandeau de jalon, `LaunchPipeline`, bouton **Récupérer le résultat** (`POST …/collect`).
  Polling live (4 s) tant que le pipeline est `accepted|running|awaiting_approval` ; le
  lancement déclenche un `refetch` (board live sans refresh manuel).
- **Artefacts** (`artifacts-view.tsx`) : Brief/PRD/Architecture/Epics en Markdown, chargés à la
  demande ; bascule auto sur cet onglet à chaque jalon. Accepte un `pid` (archive).
- **Archive** (`archive-view.tsx`) : runs passés (`GET …/history`), dates créé/terminé, board
  read-only + artefacts d'un run (`…/history/<pid>[/artifact/<key>]`). Cf. [ADR 0008](../adr/0008-persistance-reprise-archive-pipelines.md).
- **Tokens** (`token-stat.tsx`) : consommation ↑ entrée / ↓ sortie par story, somme par epic,
  total pipeline ; agrégés sur le **Dashboard** (`app/(dash)/page.tsx`).

## Gotchas (Next 16 / base-ui)

- shadcn bâti sur **@base-ui** (pas Radix) : les `Trigger` n'acceptent **pas** `asChild` →
  appliquer les classes via `buttonVariants(...)` sur le `Trigger` (sinon `npm run build`
  échoue). `Dialog`/`AlertDialog` interactifs : **contrôler** l'état `open` pour fermer après
  une action async (l'`Action` ne ferme pas tout seul). `DialogContent` impose `sm:max-w-sm`
  → surcharger le variant `sm:` pour élargir un popup.
- **Vérifier les builds** : un `docker compose build webui` qui échoue laisse l'ancien
  conteneur tourner (HTTP 200 trompeur). Confirmer l'image neuve + son contenu avant de conclure.

## Notes

- **CGU** : le chat Claude passe par le bridge `claude -p` (forfait), **jamais** l'API.
  Les modèles locaux via LiteLLM.
- **Sécurité** : exposé uniquement sur `127.0.0.1`. Une exposition LAN/mobile nécessiterait
  TLS + durcissement (nouvel ADR).
- **Next 16** : Turbopack par défaut, `params`/`searchParams`/`cookies()` asynchrones,
  convention `middleware` dépréciée (cf. `services/webui/AGENTS.md`).
