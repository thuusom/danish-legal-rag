# How to human

This project is built primarily through dialogue with Claude (an AI assistant
in Claude Code). Claude orchestrates work across specialized agents — backend,
frontend, pm, release — defined in `CLAUDE.md`. This document explains how
humans participate.

## The dialogue model

Work happens in conversation:

1. **Human expresses intent.** Either a question ("how does X work?") or
   a desired outcome ("add live law fetching from retsinformation.dk").
2. **Claude responds proportionally.**
   - For questions: a direct answer, sometimes with a follow-up offer.
   - For non-trivial work: a plan first — what would be built, in what
     order, what trade-offs, what's unclear.
3. **Human refines the plan.** Common moves: "What are the trade-offs?",
   "Why would that take 3 days?", "Use option B instead", "Skip step 4".
4. **Human says go.** A clear approval signal: "go", "do it", "proceed".
5. **Claude distributes work.** Files GitHub Issues per the rules in
   `CLAUDE.md`, then dispatches the right agents (backend, frontend, pm,
   release) to implement.
6. **Claude reports back.** Summary of what was done, files touched, tests
   run, any deviations from plan.
7. **Human reviews.** Approves, asks for changes, or moves to the next thing.

## What only humans do

Some actions are intentionally human-only because they are irreversible
or carry external consequences:

- **Push git tags** — triggers the release workflow; cannot be unpushed cleanly
- **Merge PRs to main** — agents prepare PRs; humans merge
- **Approve large architectural changes** — ADRs need human sign-off
- **Rotate secrets** — GHCR tokens, API keys
- **Talk to external stakeholders** — file an external bug, contact a vendor

The complete tag-push rule is documented in `CLAUDE.md` under coordination
model and in `docs/decisions/ADR-006-tag-driven-release.md`.

## What agents must require from humans

Agents must stop and request explicit human approval at these gates. They
do NOT proceed past any of these on their own initiative:

| Gate | When | Why |
|---|---|---|
| **Plan approval** | Before filing issues or writing code for any non-trivial work | Stops the agent from over-engineering or building the wrong thing |
| **Branch creation for a major effort** | Before starting a multi-issue feature branch | Branch naming and scope deserve a human eye; small fixes on existing branches don't need this |
| **Scope expansion mid-work** | When the agent finds the work is bigger than the original plan | Prevents silent scope creep |
| **Cross-boundary edits** | When a change requires touching files outside the agent's owned paths | Per `CLAUDE.md` ownership; the agent writes a note, the right agent or human edits |
| **Pushing the release tag** | When a release commit is merged | The only step that triggers `release.yml` and publishes images |
| **Merging PRs to main** | After review | The agent never merges its own PR |
| **Closing issues that were not auto-closed** | When manual cleanup is needed | Human decides whether the work actually satisfied the acceptance criteria |
| **Force-push, branch deletion, history rewrites** | Always | Destructive git operations |
| **Rotating or installing secrets** | Adding `GHCR_TOKEN`, `ANTHROPIC_API_KEY`, etc. | Touches credentials |
| **Spending money** | Switching to a paid LLM model, pulling large datasets | Direct cost impact |
| **Touching production data** | Anything that mutates the live Qdrant index, the cache volume in prod, etc. | Real-world consequences |
| **Overriding an ADR** | When an existing ADR is in the way | Write a new ADR that supersedes it; do not silently change behaviour |

If an agent is unsure whether something needs approval, the default is
**ask**. Cost of asking once: a single chat message. Cost of acting
without approval on the wrong thing: cleanup, rollback, or worse.

## What agents do

Agents handle the mechanical and structured work:

- Implement against accepted GitHub Issues
- File new issues from approved plans
- Run multi-step processes (release prep, ingestion checks, contract regeneration)
- Maintain documentation that follows from decisions already made
- Run tests, lint, type-check before reporting "done"

Agents NEVER:

- Decide major architecture without a human-approved plan
- Push tags (see above)
- Skip the issue-tracking rule (issues before work)

## Refining specs in dialogue

Patterns that work well:

| Phrase | Effect |
|---|---|
| "Make a plan first" | Forces Claude to enumerate scope and trade-offs before any work |
| "What are the trade-offs?" | Surfaces alternatives that may not have been mentioned |
| "Why X days?" | Challenges effort estimates (often padded for hypothetical work) |
| "Skip / merge / split that" | Reshapes the plan |
| "Go" / "Do it" / "Proceed" | Approval to start work |
| "How will this be tested?" | Forces explicit verification before "done" |
| "What did you NOT do?" | Surfaces unlisted scope cuts or deviations |

## Where things live

- `CLAUDE.md` — durable rules every agent loads at startup; ownership,
  contract-first, issue-tracking, auto-close syntax, "where decisions live"
- `docs/decisions/` — Architectural Decision Records (ADRs)
- `docs/github-workflows.md` — what each `.github/workflows/*.yml` does
- `docs/release-process.md` — the release runbook
- `.claude/agents/` — agent persona files
- `tickets/` and GitHub Issues — work in progress

## Reading order for new humans

1. `README.md` — what this project is
2. This file — how to engage with it
3. `CLAUDE.md` — agent rules (helpful even for humans)
4. `docs/decisions/README.md` — past decisions and their reasoning
