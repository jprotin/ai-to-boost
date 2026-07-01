# Service de requête RAG (FastEmbed nomic + Qdrant). Le modèle est téléchargé au
# 1er démarrage dans /cache (volume) pour éviter de le retélécharger.
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir "qdrant-client[fastembed]>=1.12"

COPY server.py /app/server.py

ENV FASTEMBED_CACHE_PATH=/cache \
    RAG_PORT=8100

EXPOSE 8100

CMD ["python", "/app/server.py"]
