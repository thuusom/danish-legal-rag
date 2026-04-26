---
name: Backend task
about: API, ingestion, retrieval, or MCP work
title: ""
labels: backend
assignees: ''
---

## User story

As a <role>, I want <capability>, so that <value>.

## Owner

backend

## Dependencies

(Other Issue numbers this depends on, or "none")

## API contract impact

(yes/no — if yes, list new/changed endpoints and schemas; they must be
reflected in `contracts/openapi.yaml` in the FIRST commit of the PR)

## Acceptance criteria

1.
2.
3.

## Out of scope

-

## Definition of done

- [ ] Code merged to feature branch
- [ ] `contracts/openapi.yaml` updated (if applicable)
- [ ] Integration test in `tests/test_integration.py`
- [ ] `make test-integration` passes
- [ ] MCP server still works (if `/ask` or `/search` changed)
- [ ] `.env.example` updated (if new config added)
