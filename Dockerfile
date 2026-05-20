# syntax=docker/dockerfile:1.7
FROM node:20-slim AS claude-cli
RUN npm install -g @anthropic-ai/claude-code@2.1.123

FROM python:3.12-slim AS deps
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates nodejs npm && \
    rm -rf /var/lib/apt/lists/*

COPY --from=claude-cli /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js /usr/local/bin/claude

COPY --from=deps /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY main.py ./
COPY migrations ./migrations
COPY static ./static
COPY plugins ./plugins

ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "main.py"]
