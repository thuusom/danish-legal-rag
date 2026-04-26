<script lang="ts">
	import type { ChatMessage } from '$lib/stores/chat';
	import LegalReference from './LegalReference.svelte';
	import { renderMarkdown } from '$lib/utils/markdown';

	interface Props {
		message: ChatMessage;
	}

	let { message }: Props = $props();

	// Re-parse markdown on every content change (streaming-safe)
	const htmlContent = $derived(renderMarkdown(message.content));
</script>

<div class="flex gap-3" data-testid="assistant-message">
	<div
		class="flex size-8 shrink-0 items-center justify-center rounded-full bg-gray-900 text-sm font-medium text-white"
		aria-hidden="true"
	>
		JA
	</div>

	<div class="min-w-0 flex-1">
		<p class="mb-1 text-xs font-medium text-gray-400">Juridisk Assistent</p>

		<div class="prose prose-gray max-w-none overflow-x-auto prose-headings:mt-4 prose-headings:mb-2 prose-p:my-1.5 prose-table:text-sm prose-th:bg-gray-100 prose-th:px-3 prose-th:py-1.5 prose-td:px-3 prose-td:py-1.5">
			{@html htmlContent}{#if message.streaming}<span class="inline-block h-4 w-0.5 animate-pulse bg-gray-600" aria-label="Skriver..." role="status"></span>{/if}
		</div>

		{#if message.references && message.references.length > 0}
			<details class="mt-4" data-testid="references-list">
				<summary class="flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold text-gray-600 select-none hover:text-gray-900 [&::-webkit-details-marker]:hidden">
					<svg
						class="h-4 w-4 transition-transform duration-200 [[open]>&]:rotate-90"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
						aria-hidden="true"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
					</svg>
					Kilder ({message.references.length})
				</summary>
				<div class="mt-3 space-y-3">
					{#each message.references as ref (ref.citation_label + ref.section)}
						<LegalReference reference={ref} />
					{/each}
				</div>
			</details>
		{/if}
	</div>
</div>
