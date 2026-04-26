import { test, expect } from '@playwright/test';

// These tests run against the real FastAPI backend with LLM_PROVIDER=mock.
// The API must be running at http://localhost:8000 before running these tests.

test.describe('Chat UI', () => {
	test('shows welcome state on load', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByText('Dansk Juridisk Assistent')).toBeVisible();
		await expect(page.getByTestId('chat-input')).toBeVisible();
		await expect(page.getByTestId('send-button')).toBeVisible();
	});

	test('send button is disabled when input is empty', async ({ page }) => {
		await page.goto('/');
		const sendButton = page.getByTestId('send-button');
		await expect(sendButton).toBeDisabled();
	});

	test('can type a question and see answer with references', async ({ page }) => {
		await page.goto('/');

		// Type a question
		const input = page.getByTestId('chat-input');
		await input.fill('Hvordan afskrives software skattemæssigt?');

		// Send the question
		const sendButton = page.getByTestId('send-button');
		await expect(sendButton).toBeEnabled();
		await sendButton.click();

		// User message should appear
		const userMessage = page.getByTestId('user-message');
		await expect(userMessage).toBeVisible();
		await expect(userMessage).toContainText('Hvordan afskrives software skattemæssigt?');

		// Loading indicator should appear
		await expect(page.getByTestId('loading-indicator')).toBeVisible();

		// Wait for the assistant message (can take a while with real API)
		const assistantMessage = page.getByTestId('assistant-message');
		await expect(assistantMessage).toBeVisible({ timeout: 45_000 });

		// References should be displayed
		const referencesList = page.getByTestId('references-list');
		await expect(referencesList).toBeVisible({ timeout: 5_000 });

		// At least one reference link should be present
		const referenceLinks = referencesList.locator('a[target="_blank"]');
		await expect(referenceLinks.first()).toBeVisible();
	});

	test('input is disabled while waiting for response', async ({ page }) => {
		await page.goto('/');

		const input = page.getByTestId('chat-input');
		await input.fill('Test spørgsmål');
		await page.getByTestId('send-button').click();

		// Input should be disabled during request
		await expect(input).toBeDisabled();

		// Wait for response to complete
		await expect(page.getByTestId('assistant-message')).toBeVisible({ timeout: 45_000 });

		// Input should be re-enabled
		await expect(input).toBeEnabled();
	});

	test('shows error when API is unreachable', async ({ page }) => {
		// Override the API URL to a non-existent server
		await page.addInitScript(() => {
			// This won't affect the built client, so we test connection error
			// by intercepting requests to simulate failure
		});

		await page.goto('/');

		// Route the /ask endpoint to fail
		await page.route('**/ask', (route) => route.abort('connectionrefused'));

		const input = page.getByTestId('chat-input');
		await input.fill('Test fejl');
		await page.getByTestId('send-button').click();

		// Error message should appear
		const errorMessage = page.getByTestId('error-message');
		await expect(errorMessage).toBeVisible({ timeout: 10_000 });
		await expect(errorMessage).toContainText('Kunne ikke forbinde');
	});

	test('can clear conversation', async ({ page }) => {
		await page.goto('/');

		// Send a message first
		const input = page.getByTestId('chat-input');
		await input.fill('Test spørgsmål');
		await page.getByTestId('send-button').click();

		// Wait for response
		await expect(page.getByTestId('assistant-message')).toBeVisible({ timeout: 45_000 });

		// Click "Ny samtale" button
		const clearButton = page.getByText('Ny samtale');
		await expect(clearButton).toBeVisible();
		await clearButton.click();

		// Messages should be cleared
		await expect(page.getByTestId('user-message')).not.toBeVisible();
		await expect(page.getByTestId('assistant-message')).not.toBeVisible();
	});
});
