<script lang="ts">
	import { client } from '$lib/api/client';
	import type { components } from '$lib/api/schema';

	type LawSummary = components['schemas']['LawSummary'];

	interface Props {
		value: string | null;
		onchange: (lawCode: string | null) => void;
	}

	let { value, onchange }: Props = $props();

	let laws = $state<LawSummary[]>([]);
	let loading = $state(true);
	let fetchError = $state(false);

	// Fetch laws on mount
	$effect(() => {
		fetchLaws();
	});

	async function fetchLaws() {
		loading = true;
		fetchError = false;

		try {
			const { data, error } = await client.GET('/laws');

			if (error || !data) {
				fetchError = true;
				return;
			}

			laws = data.laws ?? [];
		} catch {
			fetchError = true;
		} finally {
			loading = false;
		}
	}

	function handleChange(e: Event) {
		const target = e.target as HTMLSelectElement;
		const selected = target.value || null;
		onchange(selected);
	}
</script>

<div class="flex items-center gap-2" data-testid="law-filter">
	<label
		for="law-filter-select"
		class="shrink-0 text-xs font-medium text-gray-500"
	>
		Filtrer lov:
	</label>

	{#if loading}
		<select
			id="law-filter-select"
			disabled
			class="w-full rounded-md border border-gray-300 bg-gray-100 px-2 py-1.5 text-sm text-gray-400
				sm:w-auto"
			aria-label="Indlaeser love"
			data-testid="law-filter-select"
		>
			<option>Indlaeser...</option>
		</select>
	{:else if fetchError}
		<button
			onclick={() => fetchLaws()}
			class="rounded-md border border-red-300 bg-red-50 px-2 py-1.5 text-xs text-red-700 hover:bg-red-100"
			aria-label="Kunne ikke hente love, klik for at proev igen"
			data-testid="law-filter-retry"
		>
			Fejl - proev igen
		</button>
	{:else}
		<select
			id="law-filter-select"
			value={value ?? ''}
			onchange={handleChange}
			class="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700
				focus:border-gray-500 focus:ring-1 focus:ring-gray-500 focus:outline-none
				sm:w-auto"
			aria-label="Vaelg lov at filtrere efter"
			data-testid="law-filter-select"
		>
			<option value="">Alle love</option>
			{#each laws as law (law.law_code)}
				<option value={law.law_code}>
					{law.law_name} ({law.law_code})
				</option>
			{/each}
		</select>
	{/if}
</div>
