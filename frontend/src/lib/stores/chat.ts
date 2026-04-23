import { writable, derived } from 'svelte/store';
import { client } from '$lib/api/client';
import type { components } from '$lib/api/schema';

type LegalReference = components['schemas']['LegalReference'];

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	references?: LegalReference[];
	timestamp: number;
}

export type ChatStatus = 'idle' | 'loading' | 'slow' | 'error' | 'no-sources';

interface ChatState {
	messages: ChatMessage[];
	status: ChatStatus;
	error: string | null;
}

// Sentinel text the mock LLM returns when no sources match
const NO_SOURCES_MARKERS = [
	'Jeg kunne ikke finde relevante kilder',
	'ingen relevante kilder',
	'Ingen relevante lovbestemmelser'
];

function createChatStore() {
	const { subscribe, update, set } = writable<ChatState>({
		messages: [],
		status: 'idle',
		error: null
	});

	let slowTimer: ReturnType<typeof setTimeout> | null = null;

	function clearSlowTimer() {
		if (slowTimer !== null) {
			clearTimeout(slowTimer);
			slowTimer = null;
		}
	}

	async function sendMessage(question: string, filterLaw?: string | null) {
		const trimmed = question.trim();
		if (!trimmed) return;

		// Add user message
		const userMsg: ChatMessage = {
			id: crypto.randomUUID(),
			role: 'user',
			content: trimmed,
			timestamp: Date.now()
		};

		update((s) => ({
			...s,
			messages: [...s.messages, userMsg],
			status: 'loading',
			error: null
		}));

		// Start slow timer — show "Stadig i gang..." after 5 seconds
		clearSlowTimer();
		slowTimer = setTimeout(() => {
			update((s) => {
				if (s.status === 'loading') {
					return { ...s, status: 'slow' };
				}
				return s;
			});
		}, 5000);

		try {
			const { data, error } = await client.POST('/ask', {
				body: {
					question: trimmed,
					limit: 8,
					...(filterLaw ? { filter_law: filterLaw } : {})
				}
			});

			clearSlowTimer();

			if (error || !data) {
				// Extract structured error detail from FastAPI error responses
				let detail = 'Ukendt fejl fra serveren';
				if (error && typeof error === 'object' && 'detail' in error) {
					detail = String((error as { detail: unknown }).detail);
				}

				update((s) => ({
					...s,
					status: 'error',
					error: detail
				}));
				return;
			}

			// Check for NO_SOURCES_MESSAGE case
			const isNoSources = NO_SOURCES_MARKERS.some((marker) =>
				data.answer.includes(marker)
			);

			const assistantMsg: ChatMessage = {
				id: crypto.randomUUID(),
				role: 'assistant',
				content: data.answer,
				references: data.references,
				timestamp: Date.now()
			};

			update((s) => ({
				...s,
				messages: [...s.messages, assistantMsg],
				status: isNoSources ? 'no-sources' : 'idle',
				error: null
			}));
		} catch {
			clearSlowTimer();
			update((s) => ({
				...s,
				status: 'error',
				error: 'Kunne ikke forbinde til serveren. Tjek at API-serveren kører.'
			}));
		}
	}

	function clearConversation() {
		clearSlowTimer();
		set({ messages: [], status: 'idle', error: null });
	}

	/**
	 * Replace the current messages with a given array.
	 * Used when loading a saved session into the chat view.
	 */
	function setMessages(messages: ChatMessage[]) {
		clearSlowTimer();
		set({ messages, status: 'idle', error: null });
	}

	return {
		subscribe,
		sendMessage,
		clearConversation,
		setMessages
	};
}

export const chatStore = createChatStore();

// Derived store: whether the input should be disabled
export const isInputDisabled = derived(chatStore, ($chat) =>
	$chat.status === 'loading' || $chat.status === 'slow'
);
