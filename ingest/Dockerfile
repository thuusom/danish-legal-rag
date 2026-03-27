FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy shared package first
COPY shared/ /app/shared/

# Copy ingest requirements and install
COPY ingest/requirements.txt /app/ingest/requirements.txt
RUN pip install --no-cache-dir -r /app/ingest/requirements.txt

# Copy ingest code
COPY ingest/ /app/ingest/

# Create empty __init__.py for ingest package
RUN touch /app/ingest/__init__.py

ENV PYTHONPATH=/app

CMD ["python", "-m", "ingest.main"]
