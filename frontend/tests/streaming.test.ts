import { test, expect } from '@playwright/test';

// These tests run against the full docker compose stack.
// The API (with real or mock LLM) must be running at http://localhost:8000
// and the frontend preview at http://localhost:4173.

test.describe('Streaming chat', () => {
	test('sends a question and receives a streamed answer with references', async ({ page }) => {
		await page.goto('/');

		const input = page.getByTestId('chat-input');
		await input.fill('Hvad er reglerne for afskrivning af software?');

		const sendButton = page.getByTestId('send-button');
		await sendButton.click();

		// User message should appear
		await expect(page.getByTestId('user-message')).toBeVisible();

		// The assistant message should appear (streaming starts)
		const assistantMessage = page.getByTestId('assistant-message');
		await expect(assistantMessage).toBeVisible({ timeout: 30_000 });

		// The assistant message content should grow incrementally.
		// We check that content is non-empty at some point during streaming.
		await expect(assistantMessage).not.toHaveText('', { timeout: 30_000 });

		// Wait for streaming to complete — references should appear
		const referencesList = page.getByTestId('references-list');
		await expect(referencesList).toBeVisible({ timeout: 60_000 });

		// At least one clickable reference link should be present
		const referenceLinks = referencesList.locator('a[target="_blank"]');
		await expect(referenceLinks.first()).toBeVisible();
	});

	test('input is disabled during streaming and re-enabled after', async ({ page }) => {
		await page.goto('/');

		const input = page.getByTestId('chat-input');
		await input.fill('Hvad er afskrivningsloven?');
		await page.getByTestId('send-button').click();

		// Input should be disabled during streaming
		await expect(input).toBeDisabled();

		// Wait for the response to complete (references appear = done)
		await expect(page.getByTestId('assistant-message')).toBeVisible({ timeout: 60_000 });

		// Once streaming is done, references show up and input re-enables
		await expect(page.getByTestId('references-list')).toBeVisible({ timeout: 60_000 });
		await expect(input).toBeEnabled({ timeout: 5_000 });
	});

	test('shows error state on stream failure and re-enables input', async ({ page }) => {
		await page.goto('/');

		// Block both /ask/stream and /ask to simulate total failure
		await page.route('**/ask/stream', (route) => route.abort('connectionrefused'));
		await page.route('**/ask', (route) => route.abort('connectionrefused'));

		const input = page.getByTestId('chat-input');
		await input.fill('Test fejl under streaming');
		await page.getByTestId('send-button').click();

		// Error message should appear (fallback also fails)
		const errorMessage = page.getByTestId('error-message');
		await expect(errorMessage).toBeVisible({ timeout: 15_000 });

		// Input should be re-enabled after error
		await expect(input).toBeEnabled({ timeout: 5_000 });
	});

	test('falls back to non-streaming /ask when /ask/stream returns 404', async ({ page }) => {
		await page.goto('/');

		// Block only /ask/stream so it falls back to /ask
		await page.route('**/ask/stream', (route) =>
			route.fulfill({ status: 404, body: 'Not Found' })
		);

		const input = page.getByTestId('chat-input');
		await input.fill('Test fallback til ikke-streaming');
		await page.getByTestId('send-button').click();

		// Should still get an answer via the fallback
		const assistantMessage = page.getByTestId('assistant-message');
		await expect(assistantMessage).toBeVisible({ timeout: 45_000 });
	});
});
