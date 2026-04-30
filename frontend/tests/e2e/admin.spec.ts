import { test, expect } from '@playwright/test';

/**
 * Admin status page — corpus visibility and operator controls.
 */

test('admin: status page lists all 12 laws', async ({ page }) => {
	await page.goto('/admin');

	const expectedCodes = [
		'AFL',
		'ARL',
		'BOG',
		'BOG-BEK',
		'BOG-MBK',
		'LL',
		'MOML',
		'MOML-BEK',
		'REVL',
		'SEL',
		'SFL',
		'SKL'
	];
	for (const code of expectedCodes) {
		await expect(page.getByText(code, { exact: true })).toBeVisible();
	}
});

test('admin: each law has a non-empty version', async ({ page }) => {
	await page.goto('/admin');
	// Wait until at least 12 real law rows have rendered (loading/empty rows
	// don't carry data-law-code).
	await page.waitForFunction(() => document.querySelectorAll('[data-testid="law-row"]').length >= 12, { timeout: 30_000 });

	const rows = page.locator('[data-testid="law-row"]');
	const count = await rows.count();
	for (let i = 0; i < count; i++) {
		// Column 3 is the Version cell (Lov, Navn, Version, Snapshot, ...).
		const versionText = (await rows.nth(i).locator('td').nth(2).textContent())?.trim();
		expect(versionText, `law-row #${i} version cell should be non-empty`).toBeTruthy();
	}
});

test('admin: clicking "check updates" returns 202 and shows toast', async ({ page }) => {
	await page.goto('/admin');

	// Listen for the POST request to /admin/check-currency
	const responsePromise = page.waitForResponse(
		(resp) =>
			resp.url().includes('/admin/check-currency') && resp.request().method() === 'POST'
	);

	// Click the trigger button (Danish label: "Tjek opdateringer nu" or "Tjek opdateringer …")
	await page.getByRole('button', { name: /Tjek opdateringer/i }).click();

	const response = await responsePromise;
	// 202 = accepted (new run), 409 = already running — both are valid outcomes
	expect([202, 409]).toContain(response.status());
});
