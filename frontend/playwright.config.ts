import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for the tester-agent end-to-end harness.
 *
 * Tests live at the repository root in `tests/e2e/` so backend-driven
 * end-to-end coverage can join them later without moving files.
 *
 * Run against a local docker compose stack (frontend on port 3000),
 * or override with E2E_BASE_URL for a remote test environment.
 */
export default defineConfig({
	testDir: '../tests/e2e',
	workers: 1, // serial — backend state is shared
	reporter: [['list'], ['json', { outputFile: 'test-results/results.json' }]],
	retries: 0, // flakiness should be visible
	use: {
		baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000',
		trace: 'on-first-retry',
		screenshot: 'only-on-failure',
		headless: true
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }]
});
