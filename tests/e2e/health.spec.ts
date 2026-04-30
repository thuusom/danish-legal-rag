import { test, expect } from '@playwright/test';

/**
 * Backend smoke tests — no UI involved.
 *
 * These hit the API through the same origin the frontend uses
 * (proxied under /api in the docker compose stack).
 */

test('api responds 200 on /health', async ({ request }) => {
	const res = await request.get('/api/health');
	expect(res.status()).toBe(200);
	const json = await res.json();
	expect(json).toHaveProperty('status');
});

test('/laws returns 12 entries', async ({ request }) => {
	const res = await request.get('/api/laws');
	expect(res.status()).toBe(200);
	const json = await res.json();
	expect(Array.isArray(json.laws)).toBe(true);
	expect(json.laws.length).toBeGreaterThanOrEqual(12);
});
