<script lang="ts">
	import type { ChatMessage } from '$lib/stores/chat';
	import LegalReference from './LegalReference.svelte';

	interface Props {
		message: ChatMessage;
	}

	let { message }: Props = $props();
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

		<div class="prose-content max-w-[65ch] leading-relaxed text-gray-800 whitespace-pre-wrap">
			{message.content}{#if message.streaming}<span class="inline-block h-4 w-0.5 animate-pulse bg-gray-600" aria-label="Skriver..." role="status"></span>{/if}
		</div>

		{#if message.references && message.references.length > 0}
			<div class="mt-4 space-y-3" data-testid="references-list">
				<p class="text-sm font-semibold text-gray-600">
					Kilder ({message.references.length})
				</p>
				{#each message.references as ref (ref.citation_label + ref.section)}
					<LegalReference reference={ref} />
				{/each}
			</div>
		{/if}
	</div>
</div>
