# ADR-004: Update-only fetcher with in-repo seed

**Status:** Accepted
**Date:** 2026-04-27
**Context owner:** backend agent, reviewed by Thomas

## Context

ADR-003 commits us to `retsinformation-api.dk` as the primary law source.
That host enforces a per-IP rate limit of 20 requests/hour and 50
requests/day. The corpus is currently 12 sources; each source needs at
minimum one `versions/latest` call to check for updates, and a second
call (or one more for the base endpoint to recover `eli_uri`) when an
update is fetched.

A naïve "fetch everything on cold boot" strategy would consume most of
the daily budget on every container start, leave nothing for retries, and
make the system unbootable behind a shared NAT or in CI. It also couples
corpus availability to third-party uptime — if the API is down when a
fresh container starts, the system has no laws.

## Decision

The fetcher is **update-only**. It never performs cold-pulls.

- The 12 hand-curated `ingest/data/*.json` files remain in git as the
  first-boot seed. On a fresh container, `seed_cache_from_repo()` copies
  them into the `law_cache` volume so the system is immediately
  functional.
- The fetcher reads the cached `law_version_number` for each source,
  calls `GET /v1/lovgivning/{year}/{number}/versions/latest`, and only
  fetches and writes a new cache file when the upstream version is
  strictly greater (or `--force` is passed).
- On a steady-state daily run with no upstream changes, the fetcher uses
  exactly one request per source (12/day) — well under the 50/day budget
  with headroom for retries and ad-hoc admin "Pull updates now" clicks.
- Adding a new law to the corpus requires a one-time hand-curated seed
  JSON. After that first commit, updates are automatic.

## Consequences

**Positive:**
- Cold boots are zero-cost on the rate budget. No external dependency on
  the critical path.
- The system is bootable from a tarball with no network — useful for CI,
  air-gapped demos, and disaster recovery.
- Daily budget headroom: 12 sources × 1 check/day ≈ 12/50, leaving room
  for the average ~1-2 updates/day plus admin-triggered runs.
- `law_cache` survives container restarts; the seed only re-runs when the
  cache directory is empty.

**Negative:**
- Adding a new law is a two-step PR (seed file + manifest entry) rather
  than a single manifest edit.
- Seed files in git can drift from upstream. Mitigated by the daily
  fetcher: any drift is corrected within 24 hours of a container that
  has run the fetcher at least once.

## Alternatives considered

- **Full live-pull on cold boot, throttled.** Would burn the daily
  budget in 5-10 minutes on every fresh start, fail entirely behind
  shared IPs, and leave the system without a corpus if the upstream is
  down. Rejected.
- **Periodic full refresh (weekly `--force` run).** Useful as a
  consistency check but not a primary strategy. Can be added later
  behind a manual flag without changing the default.
