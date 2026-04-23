import { test, expect } from '@playwright/test';

// These tests run against the real FastAPI backend with LLM_PROVIDER=mock.
// The API must be running at http://localhost:8000 before running these tests.

test.describe('Session history sidebar', () => {
	test.beforeEach(async ({ page }) => {
		// Clear localStorage before each test
		await page.goto('/');
		await page.evaluate(() => localStorage.clear());
		await page.reload();
	});

	test('shows empty state in sidebar', async ({ page }) => {
		await page.goto('/');
		// On desktop, sidebar is always visible
		await page.setViewportSize({ width: 1280, height: 720 });
		await expect(page.getByText('Ingen samtaler endnu.')).toBeVisible();
	});

	test('creates a session when sending a message', async ({ page }) => {
		await page.setViewportSize({ width: 1280, height: 720 });
		await page.goto('/');

		// Send a message
		const input = page.getByTestId('chat-input');
		await input.fill('Hvad er afskrivningsloven?');
		await page.getByTestId('send-button').click();

		// Wait for response
		await expect(page.getByTestId('assistant-message')).toBeVisible({
			timeout: 45_000
		});

		// Session should appear in sidebar
		const sessionItem = page.getByTestId('session-item');
		await expect(sessionItem).toBeVisible();
		await expect(sessionItem.getByTestId('session-title')).toContainText(
			'Hvad er afskrivningsloven?'
		);
	});

	test('creates two sessions and switches between them', async ({ page }) => {
		await page.setViewportSize({ width: 1280, height: 720 });
		await page.goto('/');

		// --- Session 1: ask a question ---
		const input = page.getByTestId('chat-input');
		await input.fill('Hvad er afskrivningsloven?');
		await page.getByTestId('send-button').click();
		await expect(page.getByTestId('assistant-message')).toBeVisible({
			timeout: 45_000
		});

		// --- Start a new session ---
		await page.getByTestId('new-session-button').click();

		// Chat should be cleared
		await expect(page.getByTestId('user-message')).not.toBeVisible();

		// --- Session 2: ask a different question ---
		await input.fill('Hvad er årsregnskabsloven?');
		await page.getByTestId('send-button').click();
		await expect(page.getByTestId('assistant-message')).toBeVisible({
			timeout: 45_000
		});

		// Both sessions should be in the sidebar
		const sessionItems = page.getByTestId('session-item');
		await expect(sessionItems).toHaveCount(2);

		// --- Switch back to session 1 ---
		// Session 1 should contain "Hvad er afskrivningsloven?"
		const session1 = sessionItems.filter({
			hasText: 'afskrivningsloven'
		});
		await session1.click();

		// Verify we see the first question's messages
		const userMessage = page.getByTestId('user-message');
		await expect(userMessage).toContainText('Hvad er afskrivningsloven?');

		// --- Switch back to session 2 ---
		const session2 = sessionItems.filter({
			hasText: 'årsregnskabsloven'
		});
		await session2.click();

		await expect(userMessage).toContainText('Hvad er årsregnskabsloven?');
	});

	test('sessions persist across page reloads', async ({ page }) => {
		await page.setViewportSize({ width: 1280, height: 720 });
		await page.goto('/');

		// Send a message
		const input = page.getByTestId('chat-input');
		await input.fill('Test af sessionlagring');
		await page.getByTestId('send-button').click();
		await expect(page.getByTestId('assistant-message')).toBeVisible({
			timeout: 45_000
		});

		// Reload the page
		await page.reload();

		// Session should still be in sidebar
		const sessionItem = page.getByTestId('session-item');
		await expect(sessionItem).toBeVisible();
		await expect(sessionItem.getByTestId('session-title')).toContainText(
			'Test af sessionlagring'
		);

		// Messages should be restored in the chat
		await expect(page.getByTestId('user-message')).toContainText(
			'Test af sessionlagring'
		);
	});

	test('can delete a session', async ({ page }) => {
		await page.setViewportSize({ width: 1280, height: 720 });
		await page.goto('/');

		// Send a message to create a session
		const input = page.getByTestId('chat-input');
		await input.fill('Sletbar samtale');
		await page.getByTestId('send-button').click();
		await expect(page.getByTestId('assistant-message')).toBeVisible({
			timeout: 45_000
		});

		// Session should be visible
		const sessionItem = page.getByTestId('session-item');
		await expect(sessionItem).toBeVisible();

		// Hover over the session to reveal delete button
		await sessionItem.hover();
		const deleteButton = page.getByTestId('delete-session');
		await deleteButton.click();

		// Session should be gone
		await expect(page.getByText('Ingen samtaler endnu.')).toBeVisible();
	});

	test('mobile: sidebar toggles with button', async ({ page }) => {
		await page.setViewportSize({ width: 375, height: 667 });
		await page.goto('/');

		// Sidebar should not be visible on mobile
		const sidebar = page.getByTestId('session-sidebar');
		await expect(sidebar).toHaveClass(/-translate-x-full/);

		// Toggle sidebar
		await page.getByTestId('sidebar-toggle').click();

		// Sidebar should now be visible
		await expect(sidebar).toHaveClass(/translate-x-0/);
	});
});
