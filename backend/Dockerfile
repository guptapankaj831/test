FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first so this layer caches when only app code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY app/ ./app/

# Chroma persists here; compose mounts a named volume over this path.
RUN mkdir -p /data/chroma

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
