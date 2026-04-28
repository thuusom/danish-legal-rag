# ADR-003: Use retsinformation-api.dk as primary law source

**Status:** Accepted
**Date:** 2026-04-27
**Context owner:** backend agent, reviewed by Thomas

## Context

The corpus is Danish tax and accounting law: 12 acts and bekendtgørelser
today, extending over time. Until now we shipped the text as 12 hand-curated
JSON files under `ingest/data/`. Maintaining those by hand does not scale
and the files drift out of date — the spike (Issue #19) found our
Afskrivningsloven seed was the original 2016 text, while the in-force
version is amendment 24 (effective 2021-01-01). Across the seed corpus we
were 3-14× short on provisions per law.

We need a programmatic source of in-force consolidated Danish law text.

Options considered:

1. **`retsinformation-api.dk`** — third-party JSON API mirroring the
   official retsinformation.dk corpus. Structured, free, no auth, but
   unofficial and rate-limited (20 req/h, 50 req/day per IP).
2. **HTML scraping of retsinformation.dk** — official source, but the HTML
   is brittle and the site explicitly discourages scraping.
3. **Official API** — does not exist for retsinformation.dk's law corpus.
4. **Continue manual curation** — does not scale; already producing stale
   data.

## Decision

Adopt `retsinformation-api.dk` as the source of truth for law text. The
in-repo `ingest/data/*.json` files are demoted to a **first-boot seed and
fallback** — they let the system run on a cold container with no network,
and they cover any source the live fetcher fails on.

The spike (`docs/spikes/retsinformation-api-mapping.md`) validated the API
schema against our `LegalChunk` model and recommended GO. The mapping is
mechanical: chapter → paragraph_group → paragraph → stk → litra flattens
into the existing `Provision` shape with string normalisation only.

## Consequences

**Positive:**
- Corpus stays current automatically — when retsinformation publishes a
  new consolidation, we pick it up on the next daily check.
- ~10× more provisions per law on first live fetch (richer text → better
  retrieval).
- New laws need a one-line `sources.yaml` entry + a one-time seed file;
  ongoing maintenance is free.

**Negative:**
- We depend on a third-party host with no SLA. If it disappears, we have
  no live source.
- Rate limits (20/h, 50/day per IP) constrain how aggressively we can
  re-fetch.
- Schema drift on their side could break ingestion. Mitigated by pydantic
  validation in `ApiLawResponse` — a drift fails loudly.

**Mitigations:**
- Persistent `law_cache` Docker volume holds the last good fetched copy.
- Seed JSON in the repo guarantees a working corpus even if the API is
  unreachable on cold boot (see ADR-004).
- The fetcher tolerates per-source failures: one law's HTTP error does not
  prevent the others from being attempted.
- A `/markdown` endpoint exists on retsinformation-api.dk as a documented
  fallback if the structured JSON parser ever breaks on a specific law.
