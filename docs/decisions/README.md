# Architecture Decision Records (ADRs)

This directory contains records of significant architectural decisions made
on the project. Each ADR follows the lightweight format: Status, Context,
Decision, Consequences.

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-qdrant-hybrid-search.md) | Qdrant for vector and hybrid search (not OpenSearch) | Accepted | 2026-04-22 |
| [ADR-002](ADR-002-client-side-session-storage.md) | Client-side session storage via localStorage | Accepted | 2026-04 |
| [ADR-003](ADR-003-retsinformation-api-as-primary-source.md) | Use retsinformation-api.dk as primary law source | Accepted | 2026-04-27 |
| [ADR-004](ADR-004-update-only-fetcher-with-seed.md) | Update-only fetcher with in-repo seed | Accepted | 2026-04-27 |
| [ADR-005](ADR-005-idempotent-reingestion.md) | Idempotent re-ingestion via per-law delete-then-insert | Accepted | 2026-04-27 |

## Writing a new ADR

When making a non-trivial architectural decision — a third-party
dependency, a data-model change with cross-cutting impact, a deviation
from a previous ADR, or any choice that future agents will need the
reasoning for — record it here.

1. Pick the next ADR number (`ls ADR-*.md` to confirm).
2. Copy the structure of an existing ADR. The minimum sections are
   Status, Context, Decision, Consequences. Add Alternatives or Follow-up
   when useful.
3. Keep it under ~400 words. ADRs are reference material, not essays.
4. Add a row to the table above.
5. Commit alongside the change that motivates the decision, not as a
   separate doc-only PR.

ADRs are immutable once Accepted. To change a decision, write a new ADR
that supersedes the old one and update the old ADR's Status to
"Superseded by ADR-NNN".
