FROM python:3.11-slim

WORKDIR /app

COPY mcp/requirements.txt /app/mcp/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp/requirements.txt

COPY mcp/ /app/mcp/

# NOTE: We intentionally do NOT set PYTHONPATH=/app here.
# The installed 'mcp' library would be shadowed by our local /app/mcp/ directory
# if /app were on sys.path. The MCP server only calls the REST API via HTTP
# and has no need to import from shared/ or ingest/.

CMD ["python", "/app/mcp/app.py"]
