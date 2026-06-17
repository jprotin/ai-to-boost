#!/bin/sh
# Init Postgres (litellm-db) — crée la base + rôle n8n au PREMIER démarrage
# (data dir vide). n8n réutilise cette instance (cf. Phase 3). Idempotent inutile
# ici : ce script ne s'exécute qu'à l'initialisation du volume.
# Sur une instance déjà initialisée, créer manuellement (cf. runbook Phase 3).
set -e

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOSQL
  CREATE ROLE n8n LOGIN PASSWORD '${N8N_DB_PASSWORD}';
  CREATE DATABASE n8n OWNER n8n;
  GRANT ALL PRIVILEGES ON DATABASE n8n TO n8n;
EOSQL
