# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

WORKDIR /app

# System deps (for building some wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy app
COPY . /app

# Default ports: Streamlit
EXPOSE 8501

# Default env overrides (can be overridden in compose/.env)
ENV DB_PATH=/app/data/rick_and_morty.db \
    QUERY_FILE_PATH=/app/options/ingestion_query \
    SCHEMA_JSON_PATH=/app/schema/tables_schema.json \
    OLLAMA_BASE_URL=http://ollama:11434 \
    OLLAMA_MODEL=llama3.1 \
    OLLAMA_NUM_PREDICT=2000 \
    OLLAMA_TEMPERATURE=0.6 \
    OLLAMA_EMBED_MODEL=nomic-embed-text

CMD ["streamlit", "run", "src/main.py", "--server.address=0.0.0.0", "--server.port=8501"]


