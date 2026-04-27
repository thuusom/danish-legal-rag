<script lang="ts">
	import { onDestroy } from 'svelte';
	import { client } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import StatusHeader from '$lib/components/admin/StatusHeader.svelte';
	import LawTable from '$lib/components/admin/LawTable.svelte';
	import Toaster from '$lib/components/Toaster.svelte';
	import { toastStore } from '$lib/stores/toast';

	type AdminStatusResponse = components['schemas']['AdminStatusResponse'];

	const POLL_INTERVAL_MS = 5000; // While a run is active or freshly triggered
	const REFRESH_INTERVAL_MS = 30_000; // Background refresh while idle

	let status = $state<AdminStatusResponse | null>(null);
	let loading = $state(true);
	let triggering = $state(false);
	let fetchError = $state<string | null>(null);

	// Track whether we recently triggered a check; bumps polling cadence
	// even before the backend reports `running` (race window).
	let recentlyTriggered = $state(false);

	let pollTimer: ReturnType<typeof setTimeout> | null = null;

	async function fetchStatus(): Promise<void> {
		try {
			const result = await client.GET('/admin/status');
			const { data, error } = result;
			const httpStatus = (result as { response?: Response }).response?.status ?? 0;
			if (error || !data) {
				fetchError = `Kunne ikke hente status (HTTP ${httpStatus}).`;
				return;
			}
			status = data;
			fetchError = null;
		} catch (e) {
			fetchError =
				e instanceof Error ? `Netværksfejl: ${e.message}` : 'Netværksfejl ved hentning af status.';
		} finally {
			loading = false;
		}
	}

	function scheduleNextPoll() {
		if (pollTimer) clearTimeout(pollTimer);

		const isRunning = status?.ingestion_status === 'running';
		const interval = isRunning || recentlyTriggered ? POLL_INTERVAL_MS : REFRESH_INTERVAL_MS;

		pollTimer = setTimeout(async () => {
			await fetchStatus();
			// Once the backend reports a non-running state, clear the
			// "recently triggered" hint and slow polling back down.
			if (status?.ingestion_status !== 'running') {
				recentlyTriggered = false;
			}
			scheduleNextPoll();
		}, interval);
	}

	async function triggerCurrencyCheck() {
		if (triggering) return;
		triggering = true;

		try {
			const { data, error, response } = await client.POST('/admin/check-currency');

			if (response.status === 202 && data) {
				toastStore.success('Kontrol startet…');
				recentlyTriggered = true;
				// Refresh immediately to pick up `ingestion_status: running`
				await fetchStatus();
				scheduleNextPoll();
				return;
			}

			if (response.status === 409) {
				toastStore.warning('Kontrol kører allerede.');
				recentlyTriggered = true;
				await fetchStatus();
				scheduleNextPoll();
				return;
			}

			// Any other unexpected status maps to error
			const message =
				error && typeof error === 'object' && 'detail' in error
					? String((error as { detail: unknown }).detail)
					: `Uventet svar (HTTP ${response.status}).`;
			toastStore.error(message);
		} catch (e) {
			toastStore.error(
				e instanceof Error
					? `Kunne ikke starte kontrol: ${e.message}`
					: 'Kunne ikke starte kontrol.'
			);
		} finally {
			triggering = false;
		}
	}

	// Initial load + start polling.
	let mounted = false;
	$effect(() => {
		if (mounted) return;
		mounted = true;
		fetchStatus().then(() => scheduleNextPoll());
	});

	onDestroy(() => {
		if (pollTimer) clearTimeout(pollTimer);
	});
</script>

<svelte:head>
	<title>Admin — Korpusstatus</title>
</svelte:head>

<Toaster />

<div class="min-h-dvh bg-gray-50">
	<header class="border-b border-gray-200 bg-white">
		<div
			class="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-4 sm:flex-row sm:items-center sm:justify-between"
		>
			<div>
				<h1 class="text-lg font-semibold text-gray-900">Admin — Korpusstatus</h1>
				<p class="text-xs text-gray-500">
					Overblik over indlæste love og fetch-status. Operatørværktøj.
				</p>
			</div>
			<a
				href="/"
				class="inline-flex items-center gap-1 self-start rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 sm:self-auto"
				data-testid="back-to-chat"
			>
				<svg
					class="size-4"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
					stroke-width="2"
					aria-hidden="true"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
				</svg>
				Tilbage til chat
			</a>
		</div>
	</header>

	<main class="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-6">
		{#if fetchError}
			<div
				class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
				role="alert"
				data-testid="fetch-error"
			>
				<div class="flex items-start justify-between gap-3">
					<p>{fetchError}</p>
					<button
						onclick={() => {
							loading = true;
							fetchStatus();
						}}
						class="shrink-0 rounded-md border border-red-300 bg-white px-2 py-1 text-xs text-red-700 hover:bg-red-100"
						data-testid="retry-fetch"
					>
						Prøv igen
					</button>
				</div>
			</div>
		{/if}

		<StatusHeader
			{status}
			{loading}
			{triggering}
			ontrigger={triggerCurrencyCheck}
		/>

		<LawTable laws={status?.laws ?? []} {loading} />

		{#if status?.last_ingestion_completed}
			<p class="text-xs text-gray-500" data-testid="last-ingestion-completed">
				Seneste indlæsning: {new Date(status.last_ingestion_completed).toLocaleString('da-DK')}
			</p>
		{/if}
	</main>
</div>
