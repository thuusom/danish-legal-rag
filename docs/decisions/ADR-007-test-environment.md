# ADR-007: Test environment definition

**Status:** Accepted
**Date:** 2026-04-30
**Context owner:** pm agent, reviewed by Thomas

## Context

ADR-006 established a tag-driven release with a human-in-the-loop final step.
That gives us a safe path from `main` to a published image, but it does not
answer the question "where does a release candidate run before Thomas pushes
the tag?". Until now, pre-release validation has been ad-hoc: spin up dev
compose locally, poke the endpoints, hope it behaves the same in prod.

A pre-release tag like `1.2.0-rc.1` is only useful if it has somewhere to
live that resembles production closely enough to catch issues, and is
isolated enough that experimentation does not affect users.

The options considered:

1. **Managed cloud test environment** — e.g. a separate ECS/Cloud Run service
   per release. Heavy operationally, paid, and our scale doesn't justify it.
2. **Reuse the dev environment.** Rejected: dev compose is what an active
   developer is using on their laptop. A test deploy must not interrupt that.
3. **Per-PR ephemeral environments.** Attractive in theory, but the cost
   (image build per PR, infra orchestration) and complexity exceed the value
   at our current scale.
4. **A single long-lived remote host running test images via compose.**
   Cheap, predictable, mirrors prod's deployment shape. Chosen.

## Decision

The test environment is a single remote host reachable via SSH, running the
full stack via `docker-compose.test.yml`.

- **Host:** identified by the `TEST_HOST` env var (e.g. `test.example.local`).
  Provisioned out-of-band; treated as a pet, not cattle.
- **Stack definition:** `docker-compose.test.yml` at repo root, modeled on
  `docker-compose.prod.yml` with these specific differences:
  - Port range **9220-9290** (avoids collision with dev compose on the same
    host if anyone ever runs both).
    - 9220 → qdrant HTTP (container 6333)
    - 9221 → qdrant GRPC (container 6334)
    - 9230 → api (container 8000)
    - 9240 → frontend (container 3000)
    - 9250-9290 reserved for future test-time services (e.g. fixtures, mock
      LLM endpoints)
  - Container, network, and volume names suffixed `-test` so test and dev
    can coexist without interfering with each other.
  - `IMAGE_TAG` has **no default**: the deploy must be explicit about which
    rc it is testing. A bare `docker compose up` with no tag set is an error,
    by design.
  - No `restart: unless-stopped`. Test failures should be visible, not
    silently auto-recovered.
- **Image source:** GHCR, the same registry as prod. Differentiation between
  "this is a candidate" and "this is the release" is the deployed tag
  (`:1.2.0-rc.1` vs `:1.2.0`), not a separate registry.
- **Reset/seed strategy:** ephemeral named volumes per deploy. The reset
  mechanism is `docker compose -f docker-compose.test.yml down -v` followed
  by `up -d`. There is no long-lived test database; each deploy starts from
  empty Qdrant and re-ingests fixtures.
- **No SSL/TLS.** The host sits on a private network. Adding TLS to the test
  env doubles its complexity without changing what it tests.
- **Required GitHub secrets:** `TEST_HOST` (the SSH target) and an SSH
  deploy key with access to that host. Provisioned in repo settings.

## Consequences

**Positive:**

- A pre-release tag has a real, network-reachable place to be exercised
  before Thomas pushes the final tag.
- Same compose shape as prod, same registry, same image format — bugs that
  only appear in containerised deploys surface in test instead of after
  release.
- Cheap. One host, one compose file, no per-PR orchestration.
- Reset is trivial and explicit: `down -v && up -d`. State drift between
  test runs is impossible.

**Negative:**

- Single-tenant test env: only one rc can be deployed at a time. If two
  rcs need parallel validation, the second waits.
- The host is a pet: provisioning, OS patching, and SSH key rotation are
  out-of-band manual tasks. Acceptable at our scale.
- No SSL means we cannot test TLS-specific behaviour (cert pinning,
  HSTS) in the test env. Mitigation: prod is the only place TLS lives,
  and TLS termination is delegated to the reverse proxy.

## Alternatives considered

- **Managed cloud test env (ECS/Cloud Run).** Rejected: too heavy for a
  two-developer project; recurring spend without proportional value.
- **Shared dev env.** Rejected: interferes with active development on
  the same machine.
- **Per-PR ephemeral envs.** Rejected: cost and infrastructure complexity
  exceed value at this stage. Revisit if the team grows.

## Follow-up

A separate ticket (#67) introduces `docker-compose.test.yml`,
`.env.test.example`, and the `.gitignore` entry for `.env.test`. A future
deploy script (`scripts/deploy-test.sh`) and CI workflow will operationalise
push-to-test on rc tags.
