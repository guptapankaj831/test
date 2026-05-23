# syntax=docker/dockerfile:1.7
#
# Backend image — FastAPI + LangGraph research graph.
# Build:  docker build -t mara-backend ./backend
# Run:    docker run --rm -p 8000:8000 --env-file ../.env mara-backend
#
# Honors $PORT at runtime so it works on any platform that injects one.
# Defaults to 8000.

# ---------- Build stage ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --upgrade pip \
 && pip install -r requirements.txt


# ---------- Runtime stage ----------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# Non-root user for the runtime process.
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app ./app

USER app

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
