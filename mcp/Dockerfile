FROM python:3.11-slim

WORKDIR /app

COPY mcp/requirements.txt /app/mcp/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp/requirements.txt

COPY mcp/ /app/mcp/
RUN touch /app/mcp/__init__.py

ENV PYTHONPATH=/app

CMD ["python", "/app/mcp/server.py"]
