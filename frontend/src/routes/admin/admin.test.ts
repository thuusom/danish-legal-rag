import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mount, unmount, flushSync, tick } from 'svelte';

// Mock the openapi-fetch client before importing the component.
vi.mock('$lib/api/client', () => {
	const mockGet = vi.fn();
	const mockPost = vi.fn();
	return {
		client: {
			GET: mockGet,
			POST: mockPost
		}
	};
});

// Component under test must be imported AFTER the mock is registered.
const { default: AdminPage } = await import('./+page.svelte');
const { client } = await import('$lib/api/client');
const { toastStore } = await import('$lib/stores/toast');

const mockGet = vi.mocked(client.GET);
const mockPost = vi.mocked(client.POST);

type AdminStatusResponse = {
	laws: Array<{
		law_code: string;
		law_name: string;
		law_title?: string | null;
		our_version?: string | null;
		our_version_number?: number | null;
		our_version_date?: string | null;
		latest_version_number?: number | null;
		latest_version_date?: string | null;
		status: 'ok' | 'outdated' | 'fetch-failed' | 'unknown';
		ingested_at?: string | null;
		provisions_count?: number;
		eli?: string | null;
		fetch_error?: string | null;
	}>;
	last_currency_check?: string | null;
	ingestion_status: 'idle' | 'running' | 'failed' | 'unknown';
	last_ingestion_completed?: string | null;
	last_ingestion_error?: string | null;
	fetcher_state: {
		calls_today: number;
		rate_limit_day: number;
		calls_this_hour: number;
		rate_limit_hour: number;
	};
};

function statusFixture(overrides: Partial<AdminStatusResponse> = {}): AdminStatusResponse {
	return {
		laws: [
			{
				law_code: 'AFL',
				law_name: 'Afskrivningsloven',
				our_version: 'LBK nr 1147 af 29/08/2016',
				our_version_number: 24,
				our_version_date: '2021-01-01',
				status: 'ok',
				provisions_count: 41
			},
			{
				law_code: 'ARL',
				law_name: 'Årsregnskabsloven',
				our_version_number: 18,
				our_version_date: '2024-06-15',
				latest_version_number: 19,
				latest_version_date: '2024-08-01',
				status: 'outdated',
				provisions_count: 120
			},
			{
				law_code: 'XYZ',
				law_name: 'Eksempellov',
				status: 'fetch-failed',
				fetch_error: 'HTTP 503 fra retsinformation.dk'
			},
			{
				law_code: 'NEW',
				law_name: 'Ny lov',
				status: 'unknown'
			}
		],
		last_currency_check: '2026-04-27T06:00:00Z',
		ingestion_status: 'idle',
		fetcher_state: {
			calls_today: 12,
			rate_limit_day: 40,
			calls_this_hour: 3,
			rate_limit_hour: 15
		},
		...overrides
	};
}

function mockGetOk(body: AdminStatusResponse) {
	mockGet.mockResolvedValue({
		data: body,
		error: undefined,
		response: new Response(JSON.stringify(body), { status: 200 })
	} as never);
}

let target: HTMLElement;
let component: ReturnType<typeof mount> | null = null;

function renderAdmin() {
	target = document.createElement('div');
	document.body.appendChild(target);
	component = mount(AdminPage, { target });
}

async function flush() {
	// Allow microtasks (the initial fetch promise + Svelte runes) to settle.
	await Promise.resolve();
	await Promise.resolve();
	await tick();
	flushSync();
}

describe('Admin page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		toastStore.clear();
	});

	afterEach(() => {
		if (component) {
			unmount(component);
			component = null;
		}
		if (target?.parentNode) target.parentNode.removeChild(target);
	});

	it('renders the header with "Korpusstatus"', async () => {
		mockGetOk(statusFixture());
		renderAdmin();
		await flush();

		const heading = target.querySelector('h1');
		expect(heading?.textContent).toContain('Korpusstatus');
	});

	it('lists laws from the /admin/status response', async () => {
		mockGetOk(statusFixture());
		renderAdmin();
		await flush();
		await flush();

		const rows = target.querySelectorAll('[data-testid="law-row"]');
		expect(rows).toHaveLength(4);
		expect(target.textContent).toContain('Afskrivningsloven');
		expect(target.textContent).toContain('Årsregnskabsloven');
	});

	it('renders status pills with the correct color classes', async () => {
		mockGetOk(statusFixture());
		renderAdmin();
		await flush();
		await flush();

		const pills = Array.from(
			target.querySelectorAll('[data-testid="status-pill"]')
		) as HTMLElement[];

		const okPill = pills.find((p) => p.dataset.status === 'ok');
		const outdatedPill = pills.find((p) => p.dataset.status === 'outdated');
		const failedPill = pills.find((p) => p.dataset.status === 'fetch-failed');
		const unknownPill = pills.find((p) => p.dataset.status === 'unknown');

		expect(okPill?.className).toContain('bg-green-100');
		expect(okPill?.textContent).toContain('Aktuel');

		expect(outdatedPill?.className).toContain('bg-amber-100');
		expect(outdatedPill?.textContent).toContain('Forældet');

		expect(failedPill?.className).toContain('bg-red-100');
		expect(failedPill?.textContent).toContain('Hentningsfejl');

		expect(unknownPill?.className).toContain('bg-gray-100');
		expect(unknownPill?.textContent).toContain('Ukendt');
	});

	it('shows the rate-limit chips with the configured budgets', async () => {
		mockGetOk(statusFixture());
		renderAdmin();
		await flush();
		await flush();

		const rateLimit = target.querySelector('[data-testid="rate-limit"]');
		expect(rateLimit?.textContent).toContain('12/40');
		expect(rateLimit?.textContent).toContain('3/15');
	});

	it('calls POST /admin/check-currency when "Tjek opdateringer nu" is clicked', async () => {
		mockGetOk(statusFixture());
		mockPost.mockResolvedValue({
			data: { status: 'started', started_at: '2026-04-27T10:00:00Z' },
			error: undefined,
			response: new Response(null, { status: 202 })
		} as never);

		renderAdmin();
		await flush();
		await flush();

		const button = target.querySelector(
			'[data-testid="trigger-currency-check"]'
		) as HTMLButtonElement;
		expect(button).toBeTruthy();
		button.click();
		await flush();

		expect(mockPost).toHaveBeenCalledWith('/admin/check-currency');
	});

	it('shows "allerede" toast when /admin/check-currency returns 409', async () => {
		mockGetOk(statusFixture());
		mockPost.mockResolvedValue({
			data: undefined,
			error: { status: 'already-running' },
			response: new Response(null, { status: 409 })
		} as never);

		renderAdmin();
		await flush();
		await flush();

		const button = target.querySelector(
			'[data-testid="trigger-currency-check"]'
		) as HTMLButtonElement;
		button.click();
		await flush();
		await flush();

		const toasts = Array.from(target.querySelectorAll('[data-testid="toast"]'));
		const text = toasts.map((t) => t.textContent ?? '').join(' ');
		expect(text.toLowerCase()).toContain('allerede');
	});

	it('disables the trigger button while ingestion is running', async () => {
		mockGetOk(statusFixture({ ingestion_status: 'running' }));
		renderAdmin();
		await flush();
		await flush();

		const button = target.querySelector(
			'[data-testid="trigger-currency-check"]'
		) as HTMLButtonElement;
		expect(button.disabled).toBe(true);
	});

	it('shows the empty-row message when no laws are configured', async () => {
		mockGetOk(statusFixture({ laws: [] }));
		renderAdmin();
		await flush();
		await flush();

		expect(target.querySelector('[data-testid="empty-row"]')).toBeTruthy();
	});

	it('shows an error banner when /admin/status fails', async () => {
		mockGet.mockResolvedValue({
			data: undefined,
			error: { detail: 'Intern fejl' },
			response: new Response(null, { status: 500 })
		} as never);

		renderAdmin();
		await flush();
		await flush();

		expect(target.querySelector('[data-testid="fetch-error"]')).toBeTruthy();
	});
});
