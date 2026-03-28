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
  └──────────┘           │  │ :stdio   │      │  Ingest job     │  │
                         │  └──────────┘      │  (one-shot,     │  │
                         │                    │  exits when done)│  │
                         └────────────────────┴─────────────────┘──┘
```

### Docker volumes

```
hf_model_cache   ← HuggingFace embedding model (~440 MB, downloaded once)
qdrant_data      ← Qdrant vector store (all chunks + embeddings)
```

---

## Ingest-jobbet: kører én gang og stopper

`ingest`-containeren er et **one-shot job** med `restart: "no"`. Det er tilsigtet:

1. Jobbet starter, henter lovteksterne, genererer embeddings og skriver alt til Qdrant
2. Når det er færdigt logger det `=== Ingestion Complete ===` og **afslutter med exit code 0**
3. Alle data lever herefter i `qdrant_data`-volumet – der er intet behov for at holde ingest kørende

```
docker compose ps
```
```
NAME                    STATUS
danish-legal-qdrant     running
danish-legal-api        running
danish-legal-mcp        running
danish-legal-ingest     exited (0)   ← korrekt og forventet
```

**Genkør ingestion** (f.eks. efter du har tilføjet nye lovtekster):
```bash
docker compose run --rm ingest
# eller:
make ingest
```
Jobbet er idempotent – uændrede paragraffer springer embedding-trinnet over (se "Idempotent ingestion" nedenfor).

---

## HuggingFace-requests: hvad og hvorfor

Systemet bruger en **lokal embedding-model** fra HuggingFace til at konvertere lovtekster og spørgsmål til vektorer. Der kræves **ingen HuggingFace API-nøgle**.

### Modellen der downloades

| Egenskab | Værdi |
|----------|-------|
| Navn | `paraphrase-multilingual-mpnet-base-v2` |
| Udgiver | `sentence-transformers` (UKP Lab) |
| Størrelse | ~440 MB |
| Sprog | Understøtter dansk og 50+ andre sprog |
| Dimensioner | 768 |
| Kræver API-nøgle | Nej – frit tilgængelig |
| Formål | Konverterer tekst → 768-dim vektor til semantisk søgning |

### Hvornår sker download?

```
Første docker compose up
  │
  ├── ingest container starter
  │     └── sentence-transformers forsøger at loade modellen
  │           └── ikke i cache → download fra huggingface.co (~440 MB)
  │                 └── gemmes i Docker-volumen: hf_model_cache
  │
  └── api container starter (parallelt)
        └── sentence-transformers forsøger at loade modellen
              └── HF_HOME peger på hf_model_cache → allerede der → ingen download
```

Fra **anden opstart og fremefter**: Modellen er i `hf_model_cache`-volumen. Der sendes kun korte metadata-requests til HuggingFace (HEAD-requests for at tjekke om modellen er opdateret) – ingen re-download.

### Hvad requesterne er

De mange `httpx`-loglinjer under opstart er HuggingFace's snapshot-download-protokol:

```
HEAD /resolve/main/modules.json          ← tjek om modellen er ændret
GET  /api/resolve-cache/…/modules.json   ← hent cache-metadata
HEAD /resolve/main/model.safetensors     ← tjek model-weights
GET  /api/models/…/xet-read-token/…      ← hent download-token
...
```

Alle requests er **read-only** og **til HuggingFace's CDN**. Der sendes ingen brugerdata.

### Kør helt offline

Sæt `TRANSFORMERS_OFFLINE=1` i `.env` efter første download for at forhindre alle HF-requests:

```env
TRANSFORMERS_OFFLINE=1
HF_DATASETS_OFFLINE=1
```

### Skift embeddingmodel

```env
# .env
EMBEDDING_PROVIDER=sentence-transformers
ST_MODEL_NAME=intfloat/multilingual-e5-large   # alternativ model
```

> ⚠️ Hvis du skifter model skal du genskabe Qdrant-kollektionen:
> `docker compose down -v && docker compose up --build`
> (vektordimensionerne ændrer sig, og eksisterende vektorer er ugyldige)

---

## Embedding strategy

Embeddings genereres **ved ingestion** for hver lovparagraf og **ved query-tid** for brugerens spørgsmål. Samme model bruges begge steder.

**Beriget embedding-input:** I stedet for kun at embedde den rå paragraftekst beriger chunkeren teksten med lovnavn og paragrafhenvisning:

```
Afskrivningsloven § 40 C, stk. 1 [EDB-programmer (software)]:
Udgifter til erhvervelse af EDB-programmer (software) kan enten fradrages fuldt ud...
```

Dette forbedrer semantisk matching for både:
- Emnebaserede forespørgsler: "software afskrivning"
- Referencebaserede forespørgsler: "hvad siger § 40 C"

---

## Laws ingested

| Code | Name | Coverage |
|------|------|----------|
| AFL | Afskrivningsloven | Tax depreciation of intangible assets including software (§ 40, § 40 C) |
| ARL | Årsregnskabsloven | Accounting/financial reporting rules for intangible assets (§ 33–37) |

The system uses local JSON files with realistic legal content based on:
- AFL: LBK nr 1147 af 29/08/2016
- ARL: LBK nr 1580 af 10/12/2015

Set `FETCH_LIVE=true` to attempt live fetching from retsinformation.dk (requires custom parsing logic).

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
docker compose up --build
```

What happens:
1. **Qdrant** starts (vector database, persists in `qdrant_data` volume)
2. **Ingest job** starts → downloads embedding model to `hf_model_cache` on first run (~440 MB) → embeds all provisions → writes to Qdrant → **exits**
3. **API** starts → loads embedding model from `hf_model_cache` (no re-download) → ready on :8000
4. **MCP server** starts → ready for Claude Desktop

### 3. Wait for ingestion

```bash
docker compose logs -f ingest
```

When you see `=== Ingestion Complete ===` and the container shows `exited (0)`, the system is ready. This is correct behaviour.

### 4. Test

```bash
curl -s http://localhost:8000/health
```

---

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

---

## Answer style (answer-style.md)

The file `answer-style.md` in the project root controls the **tone and format** of answers. It is mounted read-only into the API container and read on every request — no restart required.

Edit it freely to change style:
```bash
# Example: switch to ultra-brief legal style
cat > answer-style.md << 'EOF'
## Tone
Vær kortfattet og præcis som en Højesteretsdommer.
Ingen eksempler medmindre specifikt bedt om det.
Brug aldrig mere end 3 sætninger per punkt.
EOF
```

The file is layered on top of the immutable legal accuracy rules (never hallucinate, always cite sources). Style can change; the legal guardrails cannot.

---

## Testing without Claude (mock mode)

If you don't have an API key, the system still works — it retrieves real legal provisions but generates a template-based answer:

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
| `llama3.3:70b` | ~40 GB | ⭐⭐⭐⭐⭐ Best Danish + legal reasoning |
| `qwen2.5:32b` | ~20 GB | ⭐⭐⭐⭐ Strong multilingual, structured output |
| `qwen2.5:14b` | ~9 GB | ⭐⭐⭐ Good compromise for limited RAM |
| `mistral-nemo` | ~8 GB | ⭐⭐⭐ Fast, reasonable Danish |

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
- `legal_search` — semantic search, returns ranked provisions with citations
- `legal_answer` — ask a question, returns structured answer + references

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
│   ├── main.py        Endpoints: /ask /search /laws /health
│   ├── rag.py         RAG pipeline + LLM providers (anthropic/openai/ollama/mock)
│   ├── embeddings.py  Query-time embedding
│   └── models.py      Re-exports from shared/
├── mcp/               MCP server (Claude Desktop integration)
│   └── app.py         legal_search + legal_answer tools
├── ingest/            One-shot ingestion job (exits after completion)
│   ├── main.py        Pipeline orchestration
│   ├── chunker.py     Law JSON → LegalChunk objects
│   ├── embedder.py    Embedding providers (sentence-transformers / OpenAI)
│   ├── fetcher.py     Load laws (local file / retsinformation.dk)
│   └── data/          Local law JSON files (AFL + ARL)
├── shared/            Shared domain models and Qdrant utilities
│   ├── models.py      LegalChunk, AskRequest/Response, etc.
│   └── qdrant_utils.py Qdrant client, collection management, search
└── tests/
    ├── api.http       httpyac test file
    ├── test_integration.py  End-to-end tests
    └── test_embeddings.py   Unit tests for embeddings/chunking
```

---

## Disclaimer

This is a technical demonstration system. The legal content is based on real Danish laws but may be incomplete or outdated. Always consult a qualified legal or tax advisor for specific legal questions.
