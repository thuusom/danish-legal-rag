<script lang="ts">
	interface Props {
		disabled?: boolean;
		onsend: (question: string) => void;
	}

	let { disabled = false, onsend }: Props = $props();

	let value = $state('');

	function handleKeydown(e: KeyboardEvent) {
		// Submit on Enter without Shift; Shift+Enter inserts newline
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			submit();
		}
	}

	function submit() {
		const trimmed = value.trim();
		if (!trimmed || disabled) return;
		onsend(trimmed);
		value = '';
	}
</script>

<form
	onsubmit={(e) => { e.preventDefault(); submit(); }}
	class="flex shrink-0 gap-2 border-t border-gray-200 bg-white px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
>
	<textarea
		bind:value
		onkeydown={handleKeydown}
		{disabled}
		rows={1}
		placeholder="Stil et juridisk spørgsmål..."
		class="flex-1 resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm
			leading-relaxed placeholder:text-gray-400
			focus:border-gray-500 focus:ring-1 focus:ring-gray-500 focus:outline-none
			disabled:cursor-not-allowed disabled:opacity-50"
		aria-label="Skriv dit spørgsmål"
		data-testid="chat-input"
	></textarea>

	<button
		type="submit"
		disabled={disabled || !value.trim()}
		class="shrink-0 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white
			hover:bg-gray-700
			disabled:cursor-not-allowed disabled:opacity-40"
		aria-label="Send spørgsmål"
		data-testid="send-button"
	>
		Send
	</button>
</form>
