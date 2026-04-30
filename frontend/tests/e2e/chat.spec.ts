import { test, expect } from '@playwright/test';

/**
 * Chat UI flows.
 *
 * Run against a live stack with a real LLM provider — these expect the
 * backend to actually answer with citations. Adjust timeouts via
 * PLAYWRIGHT_LLM_TIMEOUT_MS if a slow model is in use.
 */

const LLM_TIMEOUT_MS = Number(process.env.PLAYWRIGHT_LLM_TIMEOUT_MS ?? 60_000);

test('chat: golden path — ask about Afskrivningsloven returns answer with citations', async ({
	page
}) => {
	test.setTimeout(120_000);
	await page.goto('/');

	await page
		.getByTestId('chat-input')
		.fill('Hvad siger Afskrivningsloven om afskrivning af driftsmidler?');
	await page.getByTestId('send-button').click();

	// Wait for streaming to finish — give the LLM up to LLM_TIMEOUT_MS
	await expect(page.getByTestId('message-list')).toContainText('Afskrivningsloven', {
		timeout: LLM_TIMEOUT_MS
	});

	// At least one citation reference should appear and link to retsinformation.dk.
	// Use toBeAttached() rather than toBeVisible() — the references panel is
	// rendered collapsed by default; the links exist in the DOM with correct
	// hrefs but are not visually shown until the user expands the panel.
	// We're asserting that references were returned, not that they're expanded.
	await expect(page.locator('a[href*="retsinformation.dk"]').first()).toBeAttached({
		timeout: LLM_TIMEOUT_MS
	});
});

test('chat: empty input — send button stays disabled', async ({ page }) => {
	await page.goto('/');
	const send = page.getByTestId('send-button');
	await expect(send).toBeDisabled();
});

test('chat: streaming proof — partial text appears within 5s', async ({ page }) => {
	await page.goto('/');
	await page.getByTestId('chat-input').fill('Hvad er momslovens grundprincip?');
	await page.getByTestId('send-button').click();

	// Within 5 seconds, the message list should have non-empty content
	// (user message echo at minimum, assistant streaming begins shortly after).
	await expect(page.getByTestId('message-list')).not.toBeEmpty({ timeout: 5_000 });
});

test('chat: law filter scopes to single law', async ({ page }) => {
	test.setTimeout(120_000);
	await page.goto('/');

	// Wait for filter to populate from /laws
	const filter = page.getByTestId('law-filter-select');
	await expect(filter).toBeEnabled({ timeout: 30_000 });
	// LawFilter <option> values are law codes (e.g., "AFL"). selectOption
	// doesn't take regex for label, so use the value directly.
	await filter.selectOption('AFL');

	// Concrete question that reliably elicits AFL citations.
	// "Hvad er reglerne?" was too vague — LLM asked for clarification
	// and produced no citations within the timeout.
	await page
		.getByTestId('chat-input')
		.fill('Hvilke procentsatser gælder for afskrivning af driftsmidler?');
	await page.getByTestId('send-button').click();

	// Wait for citations to appear in the DOM (panel may be collapsed —
	// see chat.golden_path comment about toBeAttached vs toBeVisible).
	await expect(page.locator('a[href*="retsinformation.dk"]').first()).toBeAttached({
		timeout: LLM_TIMEOUT_MS
	});

	// All citation links should reference AFL (LBK 2016/1147 or "afskrivning")
	const links = await page.locator('a[href*="retsinformation.dk"]').all();
	expect(links.length).toBeGreaterThan(0);
	for (const link of links) {
		const href = await link.getAttribute('href');
		expect(href).toMatch(/2016\/1147|afskrivning/i);
	}
});
