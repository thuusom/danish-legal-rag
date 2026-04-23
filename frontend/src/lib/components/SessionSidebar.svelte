<script lang="ts">
	import { sessionStore, type Session } from '$lib/stores/sessions';
	import { chatStore } from '$lib/stores/chat';

	interface Props {
		visible?: boolean;
		onclose?: () => void;
	}

	let { visible = true, onclose }: Props = $props();

	const { sessions, activeSessionId } = sessionStore;

	function handleNewSession() {
		sessionStore.createSession();
		chatStore.clearConversation();
	}

	function handleLoadSession(session: Session) {
		const messages = sessionStore.loadSession(session.id);
		if (messages) {
			chatStore.setMessages(messages);
		}
	}

	function handleDeleteSession(e: MouseEvent, id: string) {
		e.stopPropagation();
		sessionStore.deleteSession(id);

		// If we deleted the active session, clear the chat
		if ($activeSessionId === null) {
			chatStore.clearConversation();
		}
	}

	/**
	 * Format a timestamp as a relative time string in Danish.
	 */
	function relativeTime(timestamp: number): string {
		const now = Date.now();
		const diff = now - timestamp;
		const seconds = Math.floor(diff / 1000);
		const minutes = Math.floor(seconds / 60);
		const hours = Math.floor(minutes / 60);
		const days = Math.floor(hours / 24);

		if (seconds < 60) return 'Lige nu';
		if (minutes < 60) return `${minutes} min. siden`;
		if (hours < 24) return `${hours} t. siden`;
		if (days === 1) return 'I gar';
		if (days < 30) return `${days} dage siden`;
		return new Date(timestamp).toLocaleDateString('da-DK');
	}
</script>

{#if visible}
	<!-- Backdrop on mobile -->
	<div
		class="fixed inset-0 z-20 bg-black/30 lg:hidden"
		onclick={onclose}
		onkeydown={(e) => { if (e.key === 'Escape') onclose?.(); }}
		role="button"
		tabindex="-1"
		aria-label="Luk sidepanel"
	></div>
{/if}

<aside
	class="fixed top-0 left-0 z-30 flex h-full w-64 shrink-0 flex-col border-r border-gray-200 bg-gray-50 transition-transform duration-200 lg:static lg:z-auto lg:translate-x-0"
	class:translate-x-0={visible}
	class:-translate-x-full={!visible}
	data-testid="session-sidebar"
	aria-label="Samtalehistorik"
>
	<div class="flex items-center justify-between border-b border-gray-200 p-4">
		<h2 class="text-sm font-semibold text-gray-500">Samtaler</h2>
		<button
			onclick={onclose}
			class="rounded p-1 text-gray-400 hover:text-gray-600 lg:hidden"
			aria-label="Luk sidepanel"
		>
			<svg class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
			</svg>
		</button>
	</div>

	<div class="flex-1 overflow-y-auto p-2">
		{#if $sessions.length === 0}
			<p class="px-2 py-4 text-xs text-gray-400">Ingen samtaler endnu.</p>
		{:else}
			<ul class="space-y-1" role="list">
				{#each $sessions as session (session.id)}
					<li>
						<div
							onclick={() => handleLoadSession(session)}
							onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleLoadSession(session); } }}
							class="group flex w-full cursor-pointer items-start gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-gray-200"
							class:bg-gray-200={$activeSessionId === session.id}
							class:font-medium={$activeSessionId === session.id}
							data-testid="session-item"
							role="button"
							tabindex="0"
							aria-current={$activeSessionId === session.id ? 'true' : undefined}
						>
							<div class="min-w-0 flex-1">
								<p class="truncate text-gray-700" data-testid="session-title">
									{session.title}
								</p>
								<p class="text-xs text-gray-400" data-testid="session-timestamp">
									{relativeTime(session.timestamp)}
								</p>
							</div>
							<button
								onclick={(e) => handleDeleteSession(e, session.id)}
								class="shrink-0 rounded p-0.5 text-gray-300 opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
								aria-label="Slet samtale: {session.title}"
								data-testid="delete-session"
							>
								<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
									<path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
								</svg>
							</button>
						</div>
					</li>
				{/each}
			</ul>
		{/if}
	</div>

	<div class="border-t border-gray-200 p-3">
		<button
			onclick={handleNewSession}
			class="flex w-full items-center justify-center gap-2 rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-600 transition-colors hover:bg-gray-100"
			data-testid="new-session-button"
			aria-label="Start ny samtale"
		>
			<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
			</svg>
			Ny samtale
		</button>
	</div>
</aside>
