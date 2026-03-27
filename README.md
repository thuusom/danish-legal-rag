# Danish Legal RAG

A fully working Retrieval-Augmented Generation (RAG) system for Danish tax and accounting law. Ask natural language questions in Danish and receive answers grounded in actual legal provisions with precise citations (lov, §, stk.).

## Architecture

```
                         ┌─────────────────────────────────────────┐
                         │              docker-compose              │
                         │                                          │
  ┌──────────┐           │  ┌──────────┐      ┌─────────────────┐  │
  │  Client  │──HTTP────►│  │   API    │      │     Qdrant      │  │
  │(curl/    │           │  │ :8000    │◄────►│  vector store   │  │
  │ httpyac) │           │  │          │      │  :6333          │  │
  └──────────┘           │  │ FastAPI  │      └─────────────────┘  │
                         │  │ + RAG    │               ▲           │
  ┌──────────┐           │  └──────────┘               │           │
  │  Claude  │           │       ▲                     │           │
  │  Desktop │──MCP─────►│  ┌────┴─────┐               │           │
  │          │           │  │   MCP    │      ┌─────────────────┐  │
  └──────────┘           │  │ :stdio   │      │    Ingest job   │  │
                         │  └──────────┘      │ (runs once at   │  │
                         │                    │  startup)       │  │
                         │                    └─────────────────┘  │
                         └─────────────────────────────────────────┘
```

### Data flow

```
Law JSON files                   Ingest service              Qdrant
(afskrivningsloven.json)  ──►  chunk_law()           ──►  PointStruct
(aarsregnskabsloven.json)       compute_embedding_text()    (vector + payload)
                                embed() [sentence-transformers]
                                upsert_points()

User question                    API service                 LLM
"Hvad er reglerne for..."  ──►  embed_query()        ──►  Claude/GPT
                                search_similar()            answer + references
                                build_context_text()
```

## Embedding strategy

Embeddings are generated **at ingestion time** for each legal provision, and **at query time** for the user's question. The same model must be used for both.

**Enriched embedding input:** Instead of embedding only the raw provision text, the chunker enriches the text with law name and section reference:

```
Afskrivningsloven § 40 C, stk. 1 [EDB-programmer (software)]:
Udgifter til erhvervelse af EDB-programmer (software) kan enten fradrages fuldt ud...
```

This improves semantic matching for both:
- Topic-based queries: "software afskrivning"
- Reference-based queries: "hvad siger § 40 C"

**Default model:** `paraphrase-multilingual-mpnet-base-v2` (sentence-transformers, 768 dimensions, supports Danish, no API key required)

**OpenAI alternative:** Set `EMBEDDING_PROVIDER=openai` for `text-embedding-3-small` (1536 dimensions)

## Laws ingested

| Code | Name | Coverage |
|------|------|----------|
| AFL | Afskrivningsloven | Tax depreciation of intangible assets including software (§ 40, § 40 C) |
| ARL | Årsregnskabsloven | Accounting/financial reporting rules for intangible assets (§ 33–37) |

The system uses local JSON files with realistic legal content based on:
- AFL: LBK nr 1147 af 29/08/2016
- ARL: LBK nr 1580 af 10/12/2015

Set `FETCH_LIVE=true` to attempt live fetching from retsinformation.dk (requires custom parsing logic).

## Quick start

### 1. Clone and configure

```bash
cd ~/Projects/danish-legal-rag
cp .env.example .env
```

Edit `.env` and set at minimum:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Build and start

```bash
docker compose up --build
```

This will:
1. Start Qdrant (vector database)
2. Run the ingest job (downloads embedding model ~400MB on first run, then embeds all provisions)
3. Start the REST API on port 8000
4. Start the MCP server

### 3. Wait for ingestion

Watch the ingest container logs:
```bash
docker compose logs -f ingest
```

When you see `=== Ingestion Complete ===`, the system is ready.

### 4. Test

```bash
curl -s http://localhost:8000/health
```

## Usage

### REST API

**Ask a question (primary endpoint):**
```bash
curl -s -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hvordan afskrives immaterielle aktiver såsom software skattemæssigt?"}' \
  | python3 -m json.tool
```

**Semantic search (no LLM):**
```bash
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "software afskrivning", "limit": 5}' \
  | python3 -m json.tool
```

**List ingested laws:**
```bash
curl -s http://localhost:8000/laws | python3 -m json.tool
```

**Filter by law:**
```bash
curl -s -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hvad er reglerne for goodwill?", "filter_law": "AFL"}' \
  | python3 -m json.tool
```

**Swagger UI:** http://localhost:8000/docs

### httpyac tests

Install httpyac: `npm install -g httpyac`

```bash
httpyac tests/api.http --all
```

Or run individual requests from VS Code with the httpyac extension.

### Make targets

```bash
make up              # Build and start all services in background
make down            # Stop all services
make logs            # Follow all logs
make ingest          # Re-run ingestion (e.g. after adding new laws)
make test-integration  # Run integration tests inside API container
make test-embeddings   # Run embedding unit tests inside API container
make curl-test       # Quick curl test of primary question
```

## Testing without Claude (mock mode)

If you don't have an API key, the system still works — it retrieves real legal provisions but generates a template-based answer:

```bash
# In .env:
LLM_PROVIDER=mock
```

The mock answer includes all retrieved legal provisions with their full citations. The `/search` endpoint also works without any LLM.

## Running tests

After `docker compose up`:

```bash
# Integration tests (requires running services)
docker compose exec api python -m pytest /app/tests/test_integration.py -v

# Embedding unit tests (can run standalone)
docker compose exec api python -m pytest /app/tests/test_embeddings.py -v

# All tests
docker compose exec api python -m pytest /app/tests/ -v
```

## MCP configuration for Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "danish-legal-rag": {
      "command": "docker",
      "args": ["exec", "-i", "danish-legal-mcp", "python", "/app/mcp/server.py"]
    }
  }
}
```

Available MCP tools:
- `legal_search` — semantic search, returns ranked provisions with citations
- `legal_answer` — ask a question, returns structured answer + references

## LLM providers

| Provider | Env var | Notes |
|----------|---------|-------|
| anthropic (default) | `ANTHROPIC_API_KEY` | Uses `claude-opus-4-6` |
| openai | `OPENAI_API_KEY` | Uses `gpt-4o` |
| mock | none needed | Template-based, no LLM |

## Embedding providers

| Provider | Env var | Model | Dimensions | Notes |
|----------|---------|-------|------------|-------|
| sentence-transformers (default) | none | paraphrase-multilingual-mpnet-base-v2 | 768 | Offline, Danish support |
| openai | `OPENAI_API_KEY` | text-embedding-3-small | 1536 | Requires API key |

**Important:** The embedding provider must be the same during ingestion and at query time. If you switch providers, re-run ingestion (`make ingest` after `docker compose down -v`).

## Idempotent ingestion

The ingestion job is safe to re-run. Each chunk has:
- A **stable ID** derived from `law_code + section + subsection` (UUID5)
- A **content hash** (SHA256 of the embedding input text)

On re-ingestion, unchanged chunks are skipped. Only new or modified provisions are re-embedded.

## Project structure

```
danish-legal-rag/
├── api/               REST API (FastAPI)
│   ├── main.py        Endpoints: /ask /search /laws /health
│   ├── rag.py         RAG pipeline (embed query → retrieve → generate)
│   ├── embeddings.py  Query-time embedding
│   └── models.py      Re-exports from shared/
├── mcp/               MCP server (Claude Desktop integration)
│   └── server.py      legal_search + legal_answer tools
├── ingest/            One-shot ingestion job
│   ├── main.py        Pipeline orchestration
│   ├── chunker.py     Law JSON → LegalChunk objects
│   ├── embedder.py    Embedding providers (ST / OpenAI)
│   ├── fetcher.py     Load laws (local file / retsinformation.dk)
│   └── data/          Local law JSON files
├── shared/            Shared domain models and Qdrant utilities
│   ├── models.py      LegalChunk, AskRequest/Response, etc.
│   └── qdrant_utils.py Qdrant client, collection management, search
└── tests/
    ├── api.http       httpyac test file
    ├── test_integration.py  End-to-end tests
    └── test_embeddings.py   Unit tests for embeddings/chunking
```

## Disclaimer

This is a technical demonstration system. The legal content is based on real Danish laws but may be incomplete or outdated. Always consult a qualified legal or tax advisor for specific legal questions.
