# Test runs

This directory holds an append-only history of every test suite or
regression run by the tester agent. Each run produces one Markdown file
named `{ISO-timestamp}-{mode}-{label}.md`, where:

- `ISO-timestamp` uses UTC, colons replaced with hyphens for filesystem
  safety: `2026-04-30T14-00-00Z`
- `mode` is `suite` or `regression`
- `label` identifies the suite (`chat`, `admin`, `health`, `all`) or
  the rc tag for regression (`v1.2.0-rc.1`)

Examples:

- `2026-04-30T14-00-00Z-suite-chat.md`
- `2026-05-02T08-30-00Z-regression-v1.2.0-rc.1.md`

## Why these are committed (not gitignored)

Reports are auditable artefacts. They show what was run when, against
which version, and what the outcome was. The git history of this folder
answers: "Did we regression-test rc.3?", "When did we last verify the
admin page worked?", "What bugs surfaced and where did they go?"

Per ADR-007 and the tester persona at `.claude/agents/tester.md`, every
run produces a report file — even if all tests pass.

## Format

See the canonical template in `.claude/agents/tester.md` under the
"Test-run report template" section. The example file
`2026-04-30T14-00-00Z-example-suite-chat.md` shows the format applied.

## Cross-references

- `.claude/agents/tester.md` — the agent that writes these
- `docs/test-strategy.md` — coverage baselines used in the delta
  calculation
- `docs/test-runbook.md` (Issue #81 pending) — operator runbook
- `Makefile` — `e2e`, `e2e-suite`, `e2e-regression` targets that
  produce the raw Playwright JSON the tester parses
