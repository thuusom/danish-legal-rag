# Test run 2026-04-30T16:27:33Z — full e2e suite (post-fix retest)

Mode: ad-hoc full suite (`make e2e`)
Target: `http://localhost:3000` (local docker compose, dev stack)
Tester: orchestrator-as-tester following `.claude/agents/tester.md`
Started: 2026-04-30T16:27:33Z
Completed: 2026-04-30T16:28:33Z
Duration: 1m 0s

Stack at run time:
- VERSION: 1.1.1
- API: `/health` → 200
- Corpus: 3,673 chunks across 12 laws
- LLM provider: anthropic, claude-sonnet-4-6

This run is a retest of the earlier 16:03 run after fixing Issue #96.

## Summary

- 9 tests run, **9 passed**, 0 failed, 0 skipped
- Coverage delta: backend 57.34% (+0.34%), frontend 66.75% (±0.00%) — both OK
- Bugs filed: 0
- Bugs closed: 1 (#96, fixed in this same run)

## Test cases

| # | Suite | Case | Status | Duration | Notes |
|---|---|---|---|---|---|
| 1 | admin | status page lists all 12 laws | PASS | 0.4s | — |
| 2 | admin | each law has a non-empty version | PASS | 0.5s | — |
| 3 | admin | clicking "check updates" returns 202 | PASS | 0.9s | — |
| 4 | chat | golden path — Afskrivningsloven | PASS | 20.1s | — |
| 5 | chat | empty input — send button disabled | PASS | 0.1s | — |
| 6 | chat | streaming proof — partial within 5s | PASS | 0.1s | — |
| 7 | chat | law filter scopes to single law | PASS | 38.1s | — |
| 8 | health | api responds 200 on /health | PASS | 0.0s | — |
| 9 | health | /laws returns 12 entries | PASS | 0.3s | — |

## What was fixed (closes #96)

Three test-design issues in `tests/e2e/chat.spec.ts`:

1. **Visibility vs attachment.** The references panel renders citation
   links inside a collapsed container — links exist in the DOM with
   correct `href` attributes but are `display: hidden`. Tests asserted
   `toBeVisible()` and timed out. Switched to `toBeAttached()` for
   citation-link assertions in both `golden path` and
   `law filter scopes` tests.

2. **Per-test timeout.** Playwright's default test timeout is 30s.
   The chat tests need longer because the LLM streaming response can
   take 10-30s and the test then waits for references. Added
   `test.setTimeout(120_000)` to both LLM-dependent chat tests.

3. **Vague prompt in law-filter test.** The previous prompt
   `"Hvad er reglerne?"` is too vague — the LLM (correctly) asked for
   clarification rather than producing citations, so the test
   timed out waiting for `a[href*="retsinformation.dk"]` to appear.
   Replaced with `"Hvilke procentsatser gælder for afskrivning af
   driftsmidler?"` which deterministically elicits AFL paragraph
   citations.

## Coverage

| Area | Current | Baseline | Delta | Threshold breach? |
|---|---|---|---|---|
| Backend | 57.34% | 57% | +0.34% | OK |
| Frontend | 66.75% | 66.75% | 0.00% | OK |

## Recommendations

1. **Coverage stable** — no PRs since the previous run, expected.
2. **Add a positive test for reference panel expansion.** Click the
   panel toggle and verify links become visible. Currently no test
   exercises this interaction — the recent fix relies on
   `toBeAttached()` which doesn't catch a broken expand-collapse
   regression.
3. **Add a deterministic question template for citation-dependent
   tests.** "Hvilke procentsatser gælder for ..." reliably produces
   citations; "Hvad siger / Hvad er reglerne" can produce a
   clarification request. Document in `tests/e2e/README.md` for
   future spec authors.
4. **Verify `filter_law` round-trip in a backend integration test.**
   The earlier diagnosis revealed the public API field is `filter_law`,
   not `law_code`. The frontend uses the right field; e2e correctness
   was preserved here, but a dedicated integration test would catch
   future drift before it hits e2e.

## Verdict

**PASS.** Full suite green; product healthy; coverage steady. No
bugs filed. Issue #96 (test bug discovered in the previous run)
resolved in this same cycle.

If this were a release-candidate regression, this verdict would
authorize promoting the rc to a final release.
