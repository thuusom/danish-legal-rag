# ADR-005: Idempotent re-ingestion via per-law delete-then-insert

**Status:** Accepted
**Date:** 2026-04-27
**Context owner:** backend agent, reviewed by Thomas

## Context

When the live fetcher (ADR-003, ADR-004) detects a new version of a law
upstream, it rewrites that law's cache file. The ingestion pipeline then
re-embeds the law and writes chunks to Qdrant.

Previously the ingestion pipeline used a hash-skip optimisation: each
chunk's `embedding_content_hash` was compared against the existing point
in Qdrant, and unchanged chunks were skipped. This was cheap when the
corpus was static, but it has a correctness problem under live updates:
**chunks that disappear from a law (a repealed paragraph, a renumbered
section) are not removed from the index.** They become orphans —
retrievable, but no longer present in the canonical text. Worse, their
`source_url` still points at the new version of the law, so a user
clicking through finds the cited paragraph missing.

The spike data made this concrete: live fetches produced 3-14× more
provisions per law than the seed files contained, with substantial
renumbering. Hash-skip would have left thousands of orphan chunks.

## Decision

When ingesting a law, the pipeline first calls
`delete_chunks_by_law_code(law_code)` against the Qdrant collection,
then inserts all chunks for the new version. This is done per law, not
globally — re-ingesting AFL does not touch ARL.

The hash-skip optimisation is removed.

## Consequences

**Positive:**
- The Qdrant collection is always exactly the union of the current
  cached law files. No orphans, no stale paragraph numbers, no dangling
  citations.
- Reasoning about correctness is trivial: ingest is a pure function of
  the cache.
- Re-ingestion is per-law atomic from the user's perspective — a failed
  re-ingestion of one law does not corrupt the others.

**Negative:**
- Every re-ingestion of a changed law re-embeds all of its chunks even
  when 99% are unchanged. At our scale (~12 laws, ~3000-5000 provisions
  total post-fetch, ~30s per law on a CPU embedder) this is fine.
- Brief window during re-ingestion where a law has fewer chunks than
  normal. Acceptable for a single-user tool; would matter in a
  production multi-tenant deployment.

## Follow-up

Revisit if the corpus grows past ~100 sources or if embedding cost
becomes meaningful (e.g. switching to a larger model). At that point
the candidates are: hash-skip with explicit `tombstone` marking for
removed chunks, or a copy-on-write pattern where a new collection is
built and atomically swapped in via a Qdrant alias.
