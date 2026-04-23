<script lang="ts">
	import { client } from '$lib/api/client';

	// Health check state
	let healthStatus: string | null = $state(null);
	let healthError: string | null = $state(null);
	let loading = $state(false);

	async function checkHealth() {
		loading = true;
		healthError = null;

		try {
			const { data, error } = await client.GET('/health');
			if (error) {
				healthError = 'Kunne ikke forbinde til API';
				return;
			}
			healthStatus = data?.status ?? 'ukendt';
		} catch {
			healthError = 'Kunne ikke forbinde til API';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Dansk Juridisk Assistent</title>
</svelte:head>

<main class="mx-auto max-w-prose px-4 py-16">
	<h1 class="mb-4 text-3xl font-bold text-gray-900">
		Dansk Juridisk Assistent
	</h1>

	<p class="mb-8 leading-relaxed text-gray-600">
		Stil et skattemæssigt eller regnskabsmæssigt spørgsmål og
		få et begrundet svar med henvisninger til gældende lovgivning.
	</p>

	<div class="mb-8 rounded-lg border border-gray-200 bg-gray-50 p-6">
		<p class="mb-4 text-sm text-gray-500">
			Chat-grænsefladen er under udvikling. Brug knappen herunder
			for at bekræfte, at forbindelsen til API'et virker.
		</p>

		<button
			onclick={checkHealth}
			disabled={loading}
			class="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white
				hover:bg-gray-700 disabled:opacity-50"
		>
			{loading ? 'Tjekker...' : 'Tjek API-forbindelse'}
		</button>

		{#if healthStatus}
			<p class="mt-3 text-sm text-green-700">
				API-status: {healthStatus}
			</p>
		{/if}

		{#if healthError}
			<p class="mt-3 text-sm text-red-700">
				{healthError}
			</p>
		{/if}
	</div>
</main>
