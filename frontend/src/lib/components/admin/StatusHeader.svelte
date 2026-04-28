<script lang="ts">
	import type { components } from '$lib/api/schema';

	type AdminStatusResponse = components['schemas']['AdminStatusResponse'];
	type IngestionStatus = AdminStatusResponse['ingestion_status'];

	interface Props {
		status: AdminStatusResponse | null;
		loading: boolean;
		triggering: boolean;
		ontrigger: () => void;
	}

	let { status, loading, triggering, ontrigger }: Props = $props();

	function formatDateTime(value: string | null | undefined): string {
		if (!value) return '—';
		try {
			return new Date(value).toLocaleString('da-DK', {
				dateStyle: 'short',
				timeStyle: 'short'
			});
		} catch {
			return value;
		}
	}

	function ingestionLabel(s: IngestionStatus): string {
		switch (s) {
			case 'idle':
				return 'Inaktiv';
			case 'running':
				return 'Kører';
			case 'failed':
				return 'Fejlet';
			default:
				return 'Ukendt';
		}
	}

	function ingestionPillClass(s: IngestionStatus): string {
		switch (s) {
			case 'idle':
				return 'bg-green-100 text-green-800';
			case 'running':
				return 'bg-blue-100 text-blue-800';
			case 'failed':
				return 'bg-red-100 text-red-800';
			default:
				return 'bg-gray-100 text-gray-700';
		}
	}

	let buttonDisabled = $derived(
		triggering || loading || status?.ingestion_status === 'running'
	);

	let buttonLabel = $derived.by(() => {
		if (triggering) return 'Starter…';
		if (status?.ingestion_status === 'running') return 'Kontrol kører…';
		return 'Tjek opdateringer nu';
	});
</script>

<section
	class="flex flex-col gap-4 rounded-lg border border-gray-200 bg-white p-4 sm:flex-row sm:items-center sm:justify-between"
	data-testid="admin-status-header"
>
	<dl class="grid flex-1 grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
		<div class="flex flex-col">
			<dt class="text-xs font-medium text-gray-500">Senest opdateret</dt>
			<dd class="text-gray-800" data-testid="last-currency-check">
				{loading ? 'Indlæser…' : formatDateTime(status?.last_currency_check)}
			</dd>
		</div>

		<div class="flex flex-col">
			<dt class="text-xs font-medium text-gray-500">Indlæsningsstatus</dt>
			<dd>
				{#if loading || !status}
					<span class="text-gray-400">—</span>
				{:else}
					<span
						class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {ingestionPillClass(
							status.ingestion_status
						)}"
						data-testid="ingestion-status-pill"
					>
						{ingestionLabel(status.ingestion_status)}
					</span>
					{#if status.ingestion_status === 'failed' && status.last_ingestion_error}
						<p class="mt-1 text-xs text-red-700" data-testid="last-ingestion-error">
							{status.last_ingestion_error}
						</p>
					{/if}
				{/if}
			</dd>
		</div>

		<div class="flex flex-col">
			<dt class="text-xs font-medium text-gray-500">API-kvote</dt>
			<dd class="flex flex-wrap items-center gap-1.5 text-gray-800" data-testid="rate-limit">
				{#if loading || !status}
					<span class="text-gray-400">—</span>
				{:else}
					<span
						class="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700"
						title="Kald i dag"
					>
						{status.fetcher_state.calls_today}/{status.fetcher_state.rate_limit_day} i dag
					</span>
					<span
						class="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700"
						title="Kald denne time"
					>
						{status.fetcher_state.calls_this_hour}/{status.fetcher_state.rate_limit_hour} denne
						time
					</span>
				{/if}
			</dd>
		</div>
	</dl>

	<div class="shrink-0">
		<button
			onclick={ontrigger}
			disabled={buttonDisabled}
			class="inline-flex items-center justify-center gap-2 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 focus:ring-2 focus:ring-gray-400 focus:ring-offset-1 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
			data-testid="trigger-currency-check"
			aria-label="Tjek opdateringer nu"
		>
			{#if status?.ingestion_status === 'running' || triggering}
				<svg
					class="size-4 animate-spin text-gray-500"
					fill="none"
					viewBox="0 0 24 24"
					aria-hidden="true"
				>
					<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
					></circle>
					<path
						class="opacity-75"
						fill="currentColor"
						d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
					></path>
				</svg>
			{:else}
				<svg
					class="size-4 text-gray-500"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
					stroke-width="2"
					aria-hidden="true"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
					/>
				</svg>
			{/if}
			{buttonLabel}
		</button>
	</div>
</section>
