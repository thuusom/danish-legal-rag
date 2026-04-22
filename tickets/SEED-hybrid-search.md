# Seed GitHub Issue — file this as the first backend ticket

Copy the content below into `gh issue create`, or paste into the GitHub web
UI using the "Backend task" template.

---

**Title:** Add hybrid search (dense + BM25 sparse) to retrieval pipeline

**Labels:** backend, contract

**Body:**

## User story

As a user asking a Danish legal question, I want the retrieval step to match
both semantic meaning AND exact legal terminology (§ numbers, lov names,
technical terms like "straksafskrivning"), so that my answers are grounded
in the most precisely relevant provisions rather than just thematically
similar ones.

## Owner

backend

## Dependencies

None (first real backend ticket after agent setup).

## API contract impact

**No** — retrieval quality change is internal. `contracts/openapi.yaml`
stays the same. However, add an optional `retrieval_strategy` field
to `AskRequest` and `SearchRequest` for experimentation, defaulting to
whatever the server-side default is.

## Acceptance criteria

1. New env var `RETRIEVAL_STRATEGY=dense|hybrid`, default `dense`
2. At ingestion (`ingest/main.py`), when `RETRIEVAL_STRATEGY=hybrid`, each
   chunk is written with both a dense vector (existing) and a sparse
   BM25 vector over its embedding input text
3. Qdrant collection schema supports both vectors
   (`sparse_vectors_config={"bm25": ...}`)
4. At query time (`api/rag.py`), when hybrid is active, both vectors are
   computed for the query and fused via Qdrant's `query_points(prefetch=...)`
   with RRF
5. An eval script (`tests/eval_retrieval.py`) runs a fixed set of 15
   Danish legal questions (committed in `tests/eval_questions.json`) against
   both strategies and prints recall@5 and MRR
6. Integration test `test_hybrid_search_returns_results` passes
7. `.env.example` documents `RETRIEVAL_STRATEGY`
8. MCP server unaffected — no changes to `/ask` or `/search` response shapes
9. README section "Retrieval strategy" explains the two modes and how to
   switch (propose text in PR description; PM agent will apply)

## Out of scope

- Re-ranking with a cross-encoder (future ticket)
- Query expansion or multi-query retrieval (future ticket)
- Switching default to hybrid — that's a separate ticket after eval
  numbers are in
- Adding sparse vectors to OpenAI embedding provider (only
  sentence-transformers path for now)

## Definition of done

- [ ] Code merged to the agent-setup feature branch (or a child branch)
- [ ] `contracts/openapi.yaml` unchanged (verify with `make contract-verify`)
- [ ] `make test-integration` passes
- [ ] Eval numbers from `tests/eval_retrieval.py` posted in the PR description
- [ ] MCP server still works (`docker compose logs mcp` clean)
- [ ] `.env.example` updated
