FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy shared package
COPY shared/ /app/shared/

# Copy ingest package (for embedder reuse)
COPY ingest/ /app/ingest/
RUN touch /app/ingest/__init__.py

# Copy api requirements and install
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Copy api code
COPY api/ /app/api/
RUN touch /app/api/__init__.py

# Copy tests
COPY tests/ /app/tests/
RUN touch /app/tests/__init__.py

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
