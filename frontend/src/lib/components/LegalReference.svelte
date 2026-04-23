<script lang="ts">
	import type { components } from '$lib/api/schema';

	type LegalRef = components['schemas']['LegalReference'];

	interface Props {
		reference: LegalRef;
	}

	let { reference }: Props = $props();

	// Track whether the quote is expanded
	let expanded = $state(false);

	// Truncate quote at ~200 characters
	const TRUNCATE_LENGTH = 200;
	const needsTruncation = $derived(reference.quote.length > TRUNCATE_LENGTH);
	const displayQuote = $derived(
		expanded || !needsTruncation
			? reference.quote
			: reference.quote.slice(0, TRUNCATE_LENGTH) + '...'
	);
</script>

<div class="rounded-lg border border-gray-200 bg-gray-50 p-4">
	<div class="mb-1 flex items-start justify-between gap-2">
		<div>
			{#if reference.source_url}
				<a
					href={reference.source_url}
					target="_blank"
					rel="noopener"
					class="font-semibold text-blue-800 underline decoration-blue-300 hover:decoration-blue-600"
					aria-label="Åbn {reference.citation_label} på retsinformation.dk"
				>
					{reference.citation_label}
				</a>
			{:else}
				<span class="font-semibold text-gray-900">
					{reference.citation_label}
				</span>
			{/if}
		</div>

		{#if reference.score != null}
			<span
				class="shrink-0 rounded bg-gray-200 px-2 py-0.5 font-mono text-xs text-gray-600"
				title="Relevansscore"
			>
				{reference.score.toFixed(3)}
			</span>
		{/if}
	</div>

	<p class="mb-2 text-sm text-gray-500">
		{reference.law}
		{#if reference.law_code}
			({reference.law_code})
		{/if}
	</p>

	<blockquote class="border-l-2 border-gray-300 pl-3 font-serif text-sm leading-relaxed text-gray-700">
		{displayQuote}
	</blockquote>

	{#if needsTruncation}
		<button
			onclick={() => (expanded = !expanded)}
			class="mt-1 text-xs text-blue-700 hover:text-blue-900"
			aria-expanded={expanded}
		>
			{expanded ? 'Vis mindre' : 'Læs mere'}
		</button>
	{/if}
</div>
