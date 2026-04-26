<script lang="ts">
	import type { ChatMessage, ChatStatus } from '$lib/stores/chat';
	import AssistantMessage from './AssistantMessage.svelte';

	interface Props {
		messages: ChatMessage[];
		status: ChatStatus;
		error: string | null;
	}

	let { messages, status, error }: Props = $props();

	// Auto-scroll container ref
	let scrollContainer: HTMLDivElement | undefined = $state();

	// Derive a reactive key from messages for auto-scroll.
	// During streaming, track the last assistant message content length
	// so we scroll on every chunk append.
	const scrollKey = $derived(() => {
		const lastMsg = messages[messages.length - 1];
		if (lastMsg && lastMsg.role === 'assistant' && lastMsg.streaming) {
			return `${messages.length}-${lastMsg.content.length}`;
		}
		return `${messages.length}-${status}`;
	});

	// Scroll to bottom when messages change or streaming content grows
	$effect(() => {
		// Access the reactive key to trigger on every content change
		const _key = scrollKey();
		void _key;

		if (scrollContainer) {
			queueMicrotask(() => {
				scrollContainer!.scrollTop = scrollContainer!.scrollHeight;
			});
		}
	});
</script>

<div
	bind:this={scrollContainer}
	class="flex-1 overflow-y-auto overflow-x-hidden px-3 py-6 sm:px-4"
	data-testid="message-list"
>
	{#if messages.length === 0}
		<div class="flex h-full items-center justify-center">
			<div class="text-center">
				<h2 class="mb-2 text-xl font-semibold text-gray-700">
					Dansk Juridisk Assistent
				</h2>
				<p class="max-w-sm text-sm leading-relaxed text-gray-400">
					Stil et spørgsmål om dansk skatte- eller regnskabslovgivning,
					og få et svar med henvisninger til gældende love.
				</p>
			</div>
		</div>
	{:else}
		<div class="mx-auto max-w-[65ch] min-w-0 space-y-6">
			{#each messages as message (message.id)}
				{#if message.role === 'user'}
					<div class="flex justify-end" data-testid="user-message">
						<div class="max-w-[80%] rounded-lg bg-gray-900 px-4 py-2 text-sm leading-relaxed text-white whitespace-pre-wrap">
							{message.content}
						</div>
					</div>
				{:else}
					<AssistantMessage {message} />
				{/if}
			{/each}

			<!-- Loading / slow indicator (not shown during streaming — the cursor handles that) -->
			{#if status === 'loading' || status === 'slow'}
				<div class="flex gap-3" data-testid="loading-indicator">
					<div
						class="flex size-8 shrink-0 items-center justify-center rounded-full bg-gray-900 text-sm font-medium text-white"
						aria-hidden="true"
					>
						JA
					</div>
					<div class="flex items-center gap-2 text-sm text-gray-500">
						<span class="inline-flex gap-1" aria-label="Indlæser svar">
							<span class="animate-bounce" style="animation-delay: 0ms">.</span>
							<span class="animate-bounce" style="animation-delay: 150ms">.</span>
							<span class="animate-bounce" style="animation-delay: 300ms">.</span>
						</span>
						{#if status === 'slow'}
							<span data-testid="slow-indicator">Stadig i gang...</span>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Error state -->
			{#if status === 'error' && error}
				<div
					class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
					role="alert"
					data-testid="error-message"
				>
					<p class="font-medium">Fejl</p>
					<p>{error}</p>
				</div>
			{/if}

			<!-- No sources state -->
			{#if status === 'no-sources'}
				<div
					class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
					role="status"
					data-testid="no-sources-message"
				>
					<p class="font-medium">Ingen relevante kilder fundet</p>
					<p>Prøv at omformulere dit spørgsmål eller vær mere specifik om den lovgivning, du spørger til.</p>
				</div>
			{/if}
		</div>
	{/if}
</div>
