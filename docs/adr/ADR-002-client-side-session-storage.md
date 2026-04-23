# ADR-002: Client-Side Session Storage via localStorage

## Status

Accepted

## Context

The Danish Legal RAG chat frontend needs to persist conversation history so
users can revisit previous legal questions across page reloads. The system
currently has no authentication layer and is designed as a single-user tool
for a Danish business owner or advisor.

We need to decide where to store session data (conversation messages, session
metadata). The options considered were:

1. **localStorage** -- browser-native key-value storage, synchronous, ~5 MB
   per origin.
2. **IndexedDB** -- browser-native structured storage, asynchronous, larger
   capacity.
3. **Server-side sessions** -- backend stores sessions, requires auth and a
   new API surface.

## Decision

Use `localStorage` for MVP session persistence. Sessions are stored as a
JSON-serialized array of session objects, each containing an id, title,
messages array, and timestamp.

Key: `danish-legal-rag-sessions`

## Rationale

- **No auth exists yet.** Server-side sessions require user identity. Adding
  auth is out of scope for the current phase.
- **Single-user tool.** There is one user per browser. Cross-device sync is
  not a requirement today.
- **Quick iteration.** localStorage is synchronous, requires no additional
  dependencies, and lets us ship session history without backend changes.
- **IndexedDB is overkill.** The data is small (text messages and references).
  A typical session is under 50 KB. Even with hundreds of sessions we stay
  well within the ~5 MB localStorage limit.

## Consequences

### Positive

- Zero backend changes required. Frontend-only feature.
- Instant reads and writes -- no network latency for session operations.
- Simple implementation with no new dependencies.

### Negative

- **No cross-device sync.** Sessions exist only in the browser where they
  were created.
- **~5 MB storage limit.** If a user accumulates a very large number of long
  conversations, they could hit the limit. Mitigation: we can add a
  least-recently-used eviction policy later.
- **No server-side analytics.** We cannot observe usage patterns from session
  data without additional instrumentation.
- **Data loss on browser clear.** If the user clears browser data, sessions
  are lost.

## Follow-up

A future backend ticket (planned: "Server-side session persistence") will add
a `/sessions` API surface, likely gated behind authentication. At that point,
the frontend will migrate from localStorage to API-backed storage, using
localStorage only as a write-through cache for offline resilience.
