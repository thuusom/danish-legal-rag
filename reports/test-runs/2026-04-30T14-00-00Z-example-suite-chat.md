# Test run 2026-04-30T14:00:00Z — suite chat

> **This is an example/template, not a real run.** It illustrates the
> report format the tester agent produces. Real runs replace this with
> actual data and live in date-named files alongside.

Mode: ad-hoc suite
Target: http://localhost:3000
Tester model: sonnet
Started: 2026-04-30T14:00:00Z
Completed: 2026-04-30T14:01:32Z
Duration: 1m 32s

## Summary

- 4 tests run, 4 passed, 0 failed, 0 skipped
- Coverage not measured (suite mode; coverage runs in regression mode)
- Bugs filed: 0

## Test cases

| # | Suite | Case | Status | Duration | Notes |
|---|---|---|---|---|---|
| 1 | chat | golden path — Afskrivningsloven | PASS | 24.1s | streamed in 2.1s |
| 2 | chat | empty input — send button disabled | PASS | 0.1s | — |
| 3 | chat | streaming proof — partial within 5s | PASS | 0.1s | — |
| 4 | chat | law filter scopes to single law | PASS | 25.0s | — |

## Failures → bugs filed

None.

## Recommendations

- The chat e2e suite has no test for the law_filter clearing back to
  "Alle love" after a filtered question. Gap, suggest adding next.

## Verdict

PASS — all chat suite cases green on dev.
