# The Toad engine (server/) for Fly.io. Build from the repo root: it also needs the agent
# definition in agent/. Secrets come from `fly secrets`, never from an .env in the image.
FROM python:3.12-slim

WORKDIR /app/server
# Locked dependencies first, so code changes don't reinstall them.
COPY server/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
# The whole package source, including its data files (assets/, public/).
COPY server/pyproject.toml ./
COPY server/src ./src
RUN pip install --no-cache-dir --no-deps .
COPY agent/toad-agent.json /app/agent/toad-agent.json

ENV PORT=8787 \
    DATA_DIR=/data \
    AGENT_DEFINITION=/app/agent/toad-agent.json \
    PYTHONUNBUFFERED=1
EXPOSE 8787
# One worker: the state is one JSON file and the engine holds the single desk-phone socket.
CMD ["sh", "-c", "uvicorn toad_server.main:app --host 0.0.0.0 --port ${PORT} --no-access-log --workers 1"]
