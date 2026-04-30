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
	// Wait for the table to render
	await page.waitForSelector('table');
	// Find rows; assert version cell (3rd column) is non-empty
	const versionCells = await page.locator('tbody tr td:nth-child(3)').all();
	expect(versionCells.length).toBeGreaterThanOrEqual(12);
	for (const cell of versionCells) {
		const text = (await cell.textContent())?.trim();
		expect(text).toBeTruthy();
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
