# syntax=docker/dockerfile:1.7
#
# Frontend image — Streamlit UI that streams SSE from the backend.
# Build:  docker build -t mara-frontend ./frontend
# Run:    docker run --rm -p 8501:8501 \
#             -e MARA_API_URL=http://host.docker.internal:8000 \
#             mara-frontend
#
# Honors $PORT at runtime. Defaults to 8501. Backend URL is taken from
# $MARA_API_URL (defaults to http://127.0.0.1:8000 if unset).

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
    PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app.py ./app.py

USER app

EXPOSE 8501

CMD ["sh", "-c", "streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT:-8501}"]
