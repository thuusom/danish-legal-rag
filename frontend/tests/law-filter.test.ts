import { test, expect } from '@playwright/test';

// These tests run against the real FastAPI backend with LLM_PROVIDER=mock.
// The API must be running at http://localhost:8000 before running these tests.

test.describe('Law filter', () => {
	test('law filter dropdown is populated from /laws endpoint', async ({ page }) => {
		await page.goto('/');

		// Wait for the law filter to load
		const select = page.getByTestId('law-filter-select');
		await expect(select).toBeVisible({ timeout: 10_000 });
		await expect(select).toBeEnabled();

		// Should have "Alle love" as the default option
		const options = select.locator('option');
		await expect(options.first()).toHaveText('Alle love');

		// Should have at least one law option beyond "Alle love"
		const optionCount = await options.count();
		expect(optionCount).toBeGreaterThan(1);
	});

	test('filter by AFL, ask question, verify references are AFL only', async ({ page }) => {
		await page.goto('/');

		// Wait for the law filter to load
		const select = page.getByTestId('law-filter-select');
		await expect(select).toBeEnabled({ timeout: 10_000 });

		// Select AFL (Afskrivningsloven)
		await select.selectOption('AFL');
		await expect(select).toHaveValue('AFL');

		// Type and submit a question
		const input = page.getByTestId('chat-input');
		await input.fill('Hvordan afskrives software skattemæssigt?');
		await page.getByTestId('send-button').click();

		// Wait for the assistant message with references
		const assistantMessage = page.getByTestId('assistant-message');
		await expect(assistantMessage).toBeVisible({ timeout: 45_000 });

		const referencesList = page.getByTestId('references-list');
		await expect(referencesList).toBeVisible({ timeout: 5_000 });

		// Verify all references are from AFL
		// Each reference shows the law code in parentheses, e.g. "Afskrivningsloven (AFL)"
		const referenceItems = referencesList.locator('[class*="rounded-lg border"]');
		const count = await referenceItems.count();
		expect(count).toBeGreaterThan(0);

		for (let i = 0; i < count; i++) {
			const text = await referenceItems.nth(i).textContent();
			expect(text).toContain('AFL');
		}
	});

	test('filter reset to "Alle love" removes filter', async ({ page }) => {
		await page.goto('/');

		const select = page.getByTestId('law-filter-select');
		await expect(select).toBeEnabled({ timeout: 10_000 });

		// Select a law, then go back to "Alle love"
		await select.selectOption('AFL');
		await expect(select).toHaveValue('AFL');

		await select.selectOption('');
		await expect(select).toHaveValue('');
	});

	test('law filter is keyboard accessible', async ({ page }) => {
		await page.goto('/');

		const select = page.getByTestId('law-filter-select');
		await expect(select).toBeEnabled({ timeout: 10_000 });

		// Tab to the law filter and verify it receives focus
		await select.focus();
		await expect(select).toBeFocused();

		// Verify the select has an aria-label
		const ariaLabel = await select.getAttribute('aria-label');
		expect(ariaLabel).toBeTruthy();
	});
});
