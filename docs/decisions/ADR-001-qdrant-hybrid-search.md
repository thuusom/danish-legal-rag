# ADR-001: Qdrant for vector and hybrid search (not OpenSearch)

**Status:** Accepted
**Date:** 2026-04-22
**Context owner:** backend agent, reviewed by Thomas

## Context

The jamwithai reference implementation (which inspired several extensions to
this project) uses OpenSearch for hybrid search — combining BM25 text matching
with dense-vector semantic search via a normalization pipeline.

Our project currently uses Qdrant for pure dense-vector search. We need
hybrid search for Danish legal text where exact terminology (§ 40 C, lov
numbers, specific legal terms like "straksafskrivning") carries meaning that
dense embeddings sometimes miss.

## Decision

Add hybrid search using **Qdrant's native sparse vector support** (introduced
in Qdrant 1.10), not by migrating to OpenSearch.

At ingestion, each chunk gets both a dense vector (existing
sentence-transformers embedding) and a sparse vector (BM25 over a Danish
stopword list). At query time, both vectors are computed for the query, and
Qdrant fuses the results server-side via Reciprocal Rank Fusion (RRF).

## Consequences

**Positive:**
- No new service in docker-compose. Infrastructure stays small.
- Existing Qdrant points can be migrated in-place by adding sparse vectors
  to an existing collection via `update_collection`.
- The embedding provider abstraction in `ingest/embedder.py` extends cleanly
  to cover sparse embedding via a parallel `SparseEmbeddingProvider`.
- Single source of retrieval truth — no cross-store consistency to worry
  about.

**Negative:**
- Qdrant's BM25 story is newer than OpenSearch's. If Danish-specific
  stemming/stopword quality becomes a bottleneck, we may need to revisit.
- Loses OpenSearch's operational maturity and ecosystem (dashboards,
  monitoring plugins).

**Mitigations:**
- Ship behind a feature flag (`RETRIEVAL_STRATEGY=dense|hybrid`) so dense
  remains the default until hybrid is proven on the eval question set.
- Commit a fixed eval set (`tests/eval_questions.json`) to measure
  recall@k and MRR before flipping the default.

## Alternatives considered

- **OpenSearch sidecar:** doubles infrastructure, requires a sync pipeline,
  and the wins over Qdrant 1.10+ sparse are marginal for our corpus size.
- **Pure BM25 fallback (e.g. rank_bm25 in-process):** avoids any vector
  store change but doesn't benefit from Qdrant's server-side RRF fusion and
  keeps two retrieval code paths permanently.
