<script lang="ts">
	import { chatStore, isInputDisabled } from '$lib/stores/chat';
	import { sessionStore } from '$lib/stores/sessions';
	import MessageList from '$lib/components/MessageList.svelte';
	import ChatInput from '$lib/components/ChatInput.svelte';
	import LawFilter from '$lib/components/LawFilter.svelte';
	import SessionSidebar from '$lib/components/SessionSidebar.svelte';

	let filterLaw = $state<string | null>(null);

	function handleSubmit(question: string) {
		chatStore.sendMessage(question, filterLaw);
	}

	function handleFilterChange(lawCode: string | null) {
		filterLaw = lawCode;
	}

	// Mobile sidebar toggle
	let sidebarOpen = $state(false);

	// Auto-save messages to session store whenever chat state changes
	$effect(() => {
		const messages = $chatStore.messages;
		if (messages.length > 0) {
			sessionStore.updateCurrentSession(messages);
		}
	});

	// On mount, restore the active session if one exists
	let mounted = false;
	$effect(() => {
		if (mounted) return;
		mounted = true;
		const activeId = sessionStore.getActiveSessionId();
		if (activeId) {
			const messages = sessionStore.loadSession(activeId);
			if (messages && messages.length > 0) {
				chatStore.setMessages(messages);
			}
		}
	});
</script>

<svelte:head>
	<title>Dansk Juridisk Assistent</title>
</svelte:head>

<div class="flex h-screen">
	<!-- Session sidebar -->
	<SessionSidebar
		visible={sidebarOpen}
		onclose={() => sidebarOpen = false}
	/>

	<!-- Main chat area -->
	<main class="flex min-w-0 flex-1 flex-col">
		<!-- Toolbar with mobile menu button and law filter -->
		<div class="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-2">
			<button
				onclick={() => (sidebarOpen = !sidebarOpen)}
				class="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 lg:hidden"
				aria-label="Vis sidebar"
				data-testid="sidebar-toggle"
			>
				<svg xmlns="http://www.w3.org/2000/svg" class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16" />
				</svg>
			</button>

			<LawFilter value={filterLaw} onchange={handleFilterChange} />
		</div>

		<MessageList
			messages={$chatStore.messages}
			status={$chatStore.status}
			error={$chatStore.error}
		/>
		<ChatInput disabled={$isInputDisabled} onsubmit={handleSubmit} />
	</main>
</div>
