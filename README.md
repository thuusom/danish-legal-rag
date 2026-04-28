# Danish Legal RAG

A fully working Retrieval-Augmented Generation (RAG) system for Danish tax, accounting, and corporate law. Ask natural language questions in Danish and receive answers grounded in actual legal provisions with precise citations (law, section, stk. — Danish for subsection).

## How this project is built

This is an AI-assisted project. Most code, docs, and infrastructure are
produced through dialogue with Claude (an AI assistant), which distributes
work across specialized agents — backend, frontend, pm, release — defined
in [CLAUDE.md](CLAUDE.md). Humans set direction, review plans, approve
work, and perform irreversible actions (merging, tagging, releasing).

For how humans engage with the workflow, see [human.md](human.md).
For agent rules and ownership, see [CLAUDE.md](CLAUDE.md).

## Architecture

```
                         ┌─────────────────────────────────────────────┐
                         │              docker-compose                  │
                         │                                              │
  ┌──────────────┐       │  ┌──────────┐      ┌─────────────────┐      │
  │  Frontend    │─HTTP──│─►│   API    │      │     Qdrant      │      │
  │  SvelteKit   │       │  │ :8000    │◄────►│  vector store   │      │
  │  :3000       │       │  │          │      │  :6333          │      │
  └──────────────┘       │  │ FastAPI  │      └─────────────────┘      │
                         │  │ + RAG    │               ▲               │
  ┌──────────┐           │  └──────────┘               │               │
  │  Client  │──HTTP────►│       ▲                     │               │
  │(curl/    │           │       │                     │               │
  │ httpyac) │           │  ┌────┴─────┐               │               │
  └──────────┘           │  │   MCP    │      ┌─────────────────┐      │
                         │  │ :stdio   │      │  Ingest job     │      │
  ┌──────────┐           │  └──────────┘      │  (one-shot,     │      │
  │  Claude  │──MCP─────►│                    │  exits when done)│     │
  │  Desktop │           │                    │                  │      │
  └──────────┘           └────────────────────┴──────────────────┘─────┘
```

The SvelteKit frontend is the primary user interface. It talks to the same
FastAPI backend as curl, httpyac, and the MCP server for Claude Desktop.

### Docker volumes

```
hf_model_cache   <- HuggingFace embedding model (~440 MB, downloaded once)
qdrant_data      <- Qdrant vector store (all chunks + embeddings)
law_cache        <- Per-law JSON payloads (one file per law_code) — see below
```

### Source manifest and law cache

The set of laws to ingest is declared in [`ingest/sources.yaml`](ingest/sources.yaml).
Adding or removing a law is a one-line change in that file.

At ingestion time, the pipeline reads from a cache directory (`law_cache/` on
the host, mounted at `/cache/laws` in Docker) — not directly from
`ingest/data/*.json`. On first boot the cache is empty and gets seeded from
the in-repo JSON files declared in the manifest. Subsequent boots reuse the
cache, so the daily live-fetch job (Issue #20) can update individual files
without touching the repo. The cache location is overridable via the
`LAW_CACHE_DIR` env var.

The live fetcher (`python -m ingest.law_fetcher`, run via `make fetch-laws`) keeps `law_cache/` fresh. It reads `ingest/sources.yaml`, calls `retsinformation-api.dk` for each entry, compares versions, and only writes when a newer version is available. It writes `law_cache/currency-report.json` summarising every run, and is rate-limited under the published 20/h and 50/d budget (default 15/h, 40/d, configurable via `FETCHER_RATE_LIMIT_HOUR` / `FETCHER_RATE_LIMIT_DAY`). The fetcher never touches Qdrant — the existing idempotent ingestion job re-processes the cache on the next run.

---

## Laws ingested

The corpus covers 9 Danish laws and 3 executive orders (bekendtgorelser):

### Acts (Love)

| Code | Name | Subject |
|------|------|---------|
| AFL | Afskrivningsloven | Tax depreciation (LBK nr 1147 af 29/08/2016) |
| ARL | Aarsregnskabsloven | Financial reporting / accounting (LBK nr 1580 af 10/12/2015) |
| BOG | Bogforingsloven | Bookkeeping requirements (LOV nr 700 af 2022) |
| SEL | Selskabsskatteloven | Corporate income tax (LBK nr 1241 af 2022) |
| MOML | Momsloven | Value-added tax / VAT (LBK nr 1021 af 2019) |
| LL | Ligningsloven | Personal and corporate income tax deductions (LBK nr 1735 af 2021) |
| SKL | Skattekontrolloven | Tax reporting obligations and control (LOV nr 1535 af 2017) |
| REVL | Revisorloven | Auditor regulation (LBK nr 25 af 2024) |
| SFL | Skatteforvaltningsloven | Tax administration, appeals, deadlines (LBK nr 835 af 2022) |

### Executive orders (Bekendtgorelser)

| Code | Name | Subject |
|------|------|---------|
| BOG-BEK | Bogforingsbekendtgorelsen | Digital bookkeeping system requirements (BEK nr 2006 af 2023) |
| BOG-MBK | Mindstekravsbekendtgorelsen | Minimum voucher/receipt requirements (BEK nr 98 af 2024) |
| MOML-BEK | Momsbekendtgorelsen | VAT registration, invoicing, deductions, reporting (BEK nr 1435 af 2023) |

The system uses local JSON files with realistic legal content based on the above consolidation acts. Set `FETCH_LIVE=true` to attempt live fetching from retsinformation.dk.

---

## Quick start

### 1. Configure

```bash
cd ~/Projects/danish-legal-rag
cp .env.example .env
```

Edit `.env` and set at minimum:
```env
ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Build and start

```bash
docker compose up --build -d
```

What happens:
1. **Qdrant** starts (vector database, persists in `qdrant_data` volume)
2. **Ingest job** starts -- downloads embedding model to `hf_model_cache` on first run (~440 MB) -- embeds all provisions -- writes to Qdrant -- **exits**
3. **API** starts -- loads embedding model from `hf_model_cache` (no re-download) -- ready on :8000
4. **Frontend** starts -- SvelteKit chat UI on :3000, proxies API calls to the backend
5. **MCP server** starts -- ready for Claude Desktop

Open http://localhost:3000 in your browser.

> **Frontend dev mode:** For hot-reload during frontend development, run
> `cd frontend && npm install && npm run dev` instead (serves on :5173).

### 3. Wait for ingestion

```bash
docker compose logs -f ingest
```

When you see `=== Ingestion Complete ===` and the container shows `exited (0)`, the system is ready. This is correct behaviour.

### 4. Test

```bash
curl -s http://localhost:8000/health
```

### Full rebuild (e.g. after changing embedding model)

```bash
docker compose down -v && docker compose up --build -d
```

---

## Frontend

The frontend is a SvelteKit chat application built with TypeScript and Tailwind CSS.

Features:
- **Streaming chat:** Answers arrive token-by-token via SSE from `/ask/stream`
- **Session history:** Conversations persist in localStorage; sidebar lets you switch between sessions
- **Law filter:** Dropdown populated from `/laws` endpoint; filter questions to a specific law
- **Markdown rendering:** Assistant answers rendered as formatted markdown
- **Legal references:** Each answer shows cited provisions with law name, section, source link, and relevance score
- **Responsive:** Usable on mobile viewports (375px+)
- **Danish UI:** All user-facing copy in Danish

Types are generated from `contracts/openapi.yaml` -- the frontend never hand-writes API types.

---

## API endpoints

### REST

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/ask` | Ask a question, get a complete JSON response with answer + references |
| POST | `/ask/stream` | Ask a question, receive answer via Server-Sent Events (SSE) |
| POST | `/search` | Semantic search only (no LLM), returns ranked provisions |
| GET | `/laws` | List all ingested laws with metadata |
| GET | `/admin/status` | Operator-facing corpus state (per-law version, ingestion freshness, fetcher quota) |
| POST | `/admin/check-currency` | Trigger an ad-hoc fetcher run (returns 202; 409 if already running) |

The `/admin/*` endpoints power the admin UI (Issue #26) and ops tooling.
They are unauthenticated by design; treat them as private and gate access
at the network/ingress layer. Both rely on `law_cache/` being readable from
the api container — see PR notes if you're upgrading an existing deployment.

### `/ask/stream` SSE events

The streaming endpoint returns `text/event-stream` with four event types:

| Event | Payload | Description |
|-------|---------|-------------|
| `chunk` | `{"text": "..."}` | Partial answer text (one token or small group) |
| `references` | `[{...}, ...]` | Full references array, sent once after answer is complete |
| `done` | `{}` | Stream finished successfully |
| `error` | `{"message": "..."}` | Error during generation |

**Swagger UI:** http://localhost:8000/docs

---

## The ingest job: runs once and stops

The `ingest` container is a **one-shot job** with `restart: "no"`. This is intentional:

1. The job starts, fetches the law texts, generates embeddings, and writes everything to Qdrant
2. When it is done it logs `=== Ingestion Complete ===` and **exits with exit code 0**
3. All data then lives in the `qdrant_data` volume -- there is no need to keep ingest running

```
docker compose ps
```
```
NAME                    STATUS
danish-legal-qdrant     running
danish-legal-api        running
danish-legal-frontend   running
danish-legal-mcp        running
danish-legal-ingest     exited (0)   <- correct and expected
```

**Re-run ingestion** (e.g. after adding new law texts):
```bash
docker compose run --rm ingest
# or:
make ingest
```
The job is idempotent -- unchanged paragraphs skip the embedding step (see "Idempotent ingestion" below).

---

## Usage

### REST API

**Ask a question (primary endpoint):**
```bash
curl -s -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hvordan afskrives immaterielle aktiver sasom software skattemassigt?"}' \
  | python3 -m json.tool
```

**Streaming (SSE):**
```bash
curl -N -X POST http://localhost:8000/ask/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "Hvad er reglerne for goodwill?"}' 
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
make build           # Build containers
make logs            # Follow all logs
make ingest          # Re-run ingestion (e.g. after adding new laws)
make fetch-laws      # Run live fetcher: refresh law_cache/ from retsinformation-api.dk
make fetch-laws-dry  # Dry run of the live fetcher (no writes)
make fetch-laws-force  # Force re-fetch all laws regardless of version
make test-integration  # Run integration tests inside API container
make test-embeddings   # Run embedding unit tests inside API container
make curl-test       # Quick curl test of primary question
make contract        # Generate OpenAPI spec from FastAPI
make contract-verify # Verify contract hasn't drifted
make client          # Generate TypeScript client from contract
make frontend-dev    # Start frontend dev server
make frontend-test   # Run frontend tests
make report          # Generate daily report
make prod-build      # Build production images tagged with VERSION
make prod-push       # Push production images to GHCR
make prod-up         # Start production stack (only port 80 exposed)
make prod-down       # Stop production stack
```

---

## CI

GitHub Actions runs on push to `feat/*` branches and on pull requests to `main`.

Two jobs:
1. **Unit tests (fast, no Docker):** Runs model and chunker tests, frontend lint and type check
2. **Integration tests (Docker):** Spins up the full stack with `LLM_PROVIDER=mock`, runs API integration tests, verifies contract consistency

No API keys required -- CI uses the mock LLM provider throughout.

For the full reference covering CI, the daily law currency check,
GHCR publishing, issue templates, and branch rules, see
[`docs/github-workflows.md`](docs/github-workflows.md).

### What runs automatically

Only one component in this project runs on its own. Everything else is
reactive — triggered by a human action or a code event.

| Component | Trigger | Schedule | Autonomous? |
|---|---|---|---|
| `check-law-currency.yml` | cron + manual | Daily 06:00 UTC | **Yes — only one** |
| `ci.yml` | push to feat/*, PR to main | Per push | No (reactive) |
| `release.yml` | tag push (human action) | On tag | No (reactive) |
| Claude Code agents | chat invocation | Interactive | **No — never autonomous** |

When the daily currency check finds a law that has been updated upstream,
it opens a `Stale law: ...` GitHub Issue automatically (and auto-closes it
when the local cache catches up). The check itself does not modify the
production index — that requires a human triggering `make fetch-laws` and
then re-ingesting.

See [`docs/github-workflows.md`](docs/github-workflows.md) for full
workflow details.

---

## HuggingFace requests: what and why

The system uses a **local embedding model** from HuggingFace to convert law texts and questions into vectors. **No HuggingFace API key is required.**

### The model that gets downloaded

| Property | Value |
|----------|-------|
| Name | `paraphrase-multilingual-mpnet-base-v2` |
| Publisher | `sentence-transformers` (UKP Lab) |
| Size | ~440 MB |
| Language | Supports Danish and 50+ other languages |
| Dimensions | 768 |
| Requires API key | No -- freely available |
| Purpose | Converts text to a 768-dim vector for semantic search |

### When does the download happen?

```
First docker compose up
  |
  +-- ingest container starts
  |     +-- sentence-transformers tries to load the model
  |           +-- not in cache -> download from huggingface.co (~440 MB)
  |                 +-- stored in Docker volume: hf_model_cache
  |
  +-- api container starts (in parallel)
        +-- sentence-transformers tries to load the model
              +-- HF_HOME points at hf_model_cache -> already there -> no download
```

From the **second startup onwards**: The model lives in the `hf_model_cache` volume. Only short metadata requests are sent to HuggingFace (HEAD requests to check whether the model has been updated) -- no re-download.

### Run fully offline

Set `TRANSFORMERS_OFFLINE=1` in `.env` after the first download to prevent all HF requests:

```env
TRANSFORMERS_OFFLINE=1
HF_DATASETS_OFFLINE=1
```

### Switch embedding model

```env
# .env
EMBEDDING_PROVIDER=sentence-transformers
ST_MODEL_NAME=intfloat/multilingual-e5-large   # alternative model
```

> Note: If you change the model you must recreate the Qdrant collection:
> `docker compose down -v && docker compose up --build`
> (the vector dimensions change, and existing vectors become invalid)

---

## Embedding strategy

Embeddings are generated **at ingestion time** for each law paragraph and **at query time** for the user's question. The same model is used in both places.

**Enriched embedding input:** Instead of embedding only the raw paragraph text, the chunker enriches the text with the law name and paragraph reference:

```
Afskrivningsloven par. 40 C, stk. 1 [EDB-programmer (software)]:
Udgifter til erhvervelse af EDB-programmer (software) kan enten fradrages fuldt ud...
```

This improves semantic matching for both:
- Topic-based queries: "software afskrivning"
- Reference-based queries: "hvad siger par. 40 C"

---

## Answer style (answer-style.md)

The file `answer-style.md` in the project root controls the **tone and format** of answers. It is mounted read-only into the API container and read on every request -- no restart required.

Edit it freely to change style:
```bash
# Example: switch to ultra-brief legal style
cat > answer-style.md << 'EOF'
## Tone
Vaer kortfattet og praecis som en Hojesteretsdommer.
Ingen eksempler medmindre specifikt bedt om det.
Brug aldrig mere end 3 saetninger per punkt.
EOF
```

The file is layered on top of the immutable legal accuracy rules (never hallucinate, always cite sources). Style can change; the legal guardrails cannot.

---

## Testing without Claude (mock mode)

If you don't have an API key, the system still works -- it retrieves real legal provisions but generates a template-based answer:

```env
# .env
LLM_PROVIDER=mock
```

The mock answer shows all retrieved legal provisions with their full citations. The `/search` endpoint also works without any LLM.

---

## Ollama (local LLM)

Use a local Ollama server instead of Anthropic/OpenAI:

```env
# .env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://your-server:11434/v1
OLLAMA_MODEL=llama3.3:70b
```

Recommended models for Danish legal text:

| Model | RAM | Quality |
|-------|-----|---------|
| `llama3.3:70b` | ~40 GB | Best Danish + legal reasoning |
| `qwen2.5:32b` | ~20 GB | Strong multilingual, structured output |
| `qwen2.5:14b` | ~9 GB | Good compromise for limited RAM |
| `mistral-nemo` | ~8 GB | Fast, reasonable Danish |

Pull a model on your Ollama server:
```bash
ollama pull llama3.3:70b
```

---

## Running tests

After `docker compose up`:

```bash
# Integration tests (requires running services)
docker compose exec api python -m pytest /app/tests/test_integration.py -v

# Embedding unit tests (can run standalone)
docker compose exec api python -m pytest /app/tests/test_embeddings.py -v

# All tests
docker compose exec api python -m pytest /app/tests/ -v

# Frontend tests
cd frontend && npm run test:unit
cd frontend && npx playwright test
```

---

## MCP configuration for Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "danish-legal-rag": {
      "command": "docker",
      "args": ["exec", "-i", "danish-legal-mcp", "python", "/app/mcp/app.py"]
    }
  }
}
```

Available MCP tools:
- `legal_search` -- semantic search, returns ranked provisions with citations
- `legal_answer` -- ask a question, returns structured answer + references

---

## LLM providers

| Provider | Set in .env | Notes |
|----------|-------------|-------|
| `anthropic` (default) | `ANTHROPIC_API_KEY` | Claude, best quality |
| `openai` | `OPENAI_API_KEY` | GPT-4o |
| `ollama` | `OLLAMA_BASE_URL` + `OLLAMA_MODEL` | Local, no API key |
| `mock` | nothing | Returns raw retrieved text, no LLM |

---

## Idempotent ingestion

The ingestion job is safe to re-run. Each chunk has:
- A **stable ID** derived from `law_code + section + subsection` (UUID5)
- A **content hash** (SHA256 of the embedding input text)

On re-ingestion, unchanged chunks are skipped. Only new or modified provisions are re-embedded.

---

## Project structure

```
danish-legal-rag/
├── answer-style.md    Tone/style guide (hot-reloadable, edit freely)
├── api/               REST API (FastAPI)
│   ├── main.py        Endpoints: /ask /ask/stream /search /laws /health
│   ├── rag.py         RAG pipeline + LLM providers (anthropic/openai/ollama/mock)
│   ├── embeddings.py  Query-time embedding
│   └── models.py      Re-exports from shared/
├── frontend/          SvelteKit chat application
│   └── src/
│       ├── lib/api/   Generated TypeScript client from OpenAPI contract
│       ├── lib/       Stores, components, utilities
│       └── routes/    SvelteKit pages
├── mcp/               MCP server (Claude Desktop integration)
│   └── app.py         legal_search + legal_answer tools
├── ingest/            One-shot ingestion job (exits after completion)
│   ├── main.py        Pipeline orchestration
│   ├── chunker.py     Law JSON -> LegalChunk objects
│   ├── embedder.py    Embedding providers (sentence-transformers / OpenAI)
│   ├── fetcher.py     Load laws (local file / retsinformation.dk)
│   └── data/          Local law JSON files (12 sources)
├── shared/            Shared domain models and Qdrant utilities
│   ├── models.py      LegalChunk, AskRequest/Response, etc.
│   └── qdrant_utils.py Qdrant client, collection management, search
├── contracts/
│   └── openapi.yaml   API contract (source of truth for frontend types)
├── docs/              Architecture docs, ADRs, archived plans
├── tests/
│   ├── api.http       httpyac test file
│   ├── test_integration.py  End-to-end tests
│   └── test_embeddings.py   Unit tests for embeddings/chunking
└── .github/workflows/
    └── ci.yml         GitHub Actions CI (unit + integration)
```

---

## Disclaimer

This is a technical demonstration system. The legal content is based on real Danish laws but may be incomplete or outdated. Always consult a qualified legal or tax advisor for specific legal questions.
