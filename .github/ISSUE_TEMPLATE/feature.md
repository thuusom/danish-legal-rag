---
name: Feature
about: User-visible feature work (one or more agents)
labels: feature
---

## User story

As a <role>, I want <capability>, so that <value>.

## Owner

(backend | frontend | both)

## Dependencies

(Other Issue numbers this depends on, or "none")

## API contract impact

(yes/no — if yes, list new/changed endpoints and schemas; they must be
reflected in `contracts/openapi.yaml` in the FIRST commit of the PR.)

## Acceptance criteria

1.
2.
3.

## Out of scope

-

## Definition of done

- [ ] Code merged to feature branch
- [ ] `contracts/openapi.yaml` updated (if applicable)
- [ ] Tests added or updated (unit + integration / e2e as appropriate)
- [ ] Acceptance test plan below filled in by tester (if user-visible)
- [ ] `.spec.ts` translation under `frontend/tests/e2e/` (if user-visible)

## Acceptance test plan

The tester agent fills this in during spec review (before implementation
begins). For features that change user-visible behaviour, this section
plus a corresponding `.spec.ts` translation under `frontend/tests/e2e/`
is part of the definition of done.

### Positive cases

- [ ] Given _____, when _____, then _____

### Negative cases

- [ ] When _____ is invalid / missing / oversized, the system _____

### Edge cases

- [ ] Empty input
- [ ] Concurrent requests
- [ ] Stale cache / network failure
- [ ] User abandons mid-flow

### Notes for the tester

(Optional. Surface ambiguities here so the tester can flag them during
spec review.)
