import { writable, derived } from 'svelte/store';
import { client } from '$lib/api/client';
import type { components } from '$lib/api/schema';
import { consumeSSEStream } from '$lib/api/sse';
import { generateId } from '$lib/utils/id';

type LegalReference = components['schemas']['LegalReference'];

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	references?: LegalReference[];
	timestamp: number;
	/** True while the assistant message is still being streamed */
	streaming?: boolean;
	/** Model identifier, set on StreamDoneEvent */
	model_used?: string;
}

export type ChatStatus = 'idle' | 'loading' | 'streaming' | 'slow' | 'error' | 'no-sources';

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

// Base URL for raw fetch calls (same as the openapi-fetch client).
// Defaults to server-side proxy; override with VITE_API_BASE_URL for bare-metal dev.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';

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

	/**
	 * Build conversation history from existing messages for multi-turn context.
	 * Excludes messages that are still streaming.
	 */
	function buildHistory(
		messages: ChatMessage[]
	): { role: 'user' | 'assistant'; content: string }[] {
		return messages
			.filter((m) => !m.streaming)
			.map((m) => ({ role: m.role, content: m.content }));
	}

	/**
	 * Update the last assistant message in-place.
	 * Uses a callback so callers can append content, set references, etc.
	 */
	function updateLastAssistant(fn: (msg: ChatMessage) => ChatMessage) {
		update((s) => {
			const msgs = [...s.messages];
			for (let i = msgs.length - 1; i >= 0; i--) {
				if (msgs[i].role === 'assistant') {
					msgs[i] = fn({ ...msgs[i] });
					break;
				}
			}
			return { ...s, messages: msgs };
		});
	}

	/**
	 * Try streaming via POST /ask/stream. Returns true if successful,
	 * false if the endpoint is unavailable (so we can fall back).
	 */
	async function tryStreaming(
		question: string,
		filterLaw: string | null | undefined,
		history: { role: 'user' | 'assistant'; content: string }[]
	): Promise<boolean> {
		const body: components['schemas']['StreamAskRequest'] = {
			question,
			limit: 8,
			...(filterLaw ? { filter_law: filterLaw } : {}),
			...(history.length > 0 ? { history } : {})
		};

		let response: Response;
		try {
			response = await fetch(`${BASE_URL}/ask/stream`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			});
		} catch {
			// Network error — fall back
			return false;
		}

		if (!response.ok || !response.body) {
			// 404, 500, etc. — fall back
			return false;
		}

		// Create a placeholder assistant message in streaming state
		const assistantId = generateId();
		const assistantMsg: ChatMessage = {
			id: assistantId,
			role: 'assistant',
			content: '',
			streaming: true,
			timestamp: Date.now()
		};

		clearSlowTimer();
		update((s) => ({
			...s,
			messages: [...s.messages, assistantMsg],
			status: 'streaming',
			error: null
		}));

		await consumeSSEStream(response, {
			onChunk(data) {
				updateLastAssistant((msg) => ({
					...msg,
					content: msg.content + data
				}));
			},
			onReferences(refs) {
				updateLastAssistant((msg) => ({
					...msg,
					references: refs
				}));
			},
			onDone(data) {
				updateLastAssistant((msg) => {
					// Finalize the message
					return {
						...msg,
						streaming: false,
						model_used: data.model_used
					};
				});

				// Read the final content to determine no-sources status
				let finalStatus: ChatStatus = 'idle';
				update((s) => {
					const lastAssistant = [...s.messages]
						.reverse()
						.find((m) => m.role === 'assistant');
					if (lastAssistant) {
						const isNoSources = NO_SOURCES_MARKERS.some((marker) =>
							lastAssistant.content.includes(marker)
						);
						if (isNoSources) finalStatus = 'no-sources';
					}
					return { ...s, status: finalStatus, error: null };
				});
			},
			onError(detail) {
				updateLastAssistant((msg) => ({
					...msg,
					streaming: false
				}));
				update((s) => ({
					...s,
					status: 'error',
					error: detail
				}));
			}
		});

		return true;
	}

	/**
	 * Fallback: use the non-streaming POST /ask endpoint.
	 */
	async function fallbackAsk(
		question: string,
		filterLaw: string | null | undefined
	): Promise<void> {
		// Start slow timer
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
					question,
					limit: 8,
					...(filterLaw ? { filter_law: filterLaw } : {})
				}
			});

			clearSlowTimer();

			if (error || !data) {
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

			const isNoSources = NO_SOURCES_MARKERS.some((marker) =>
				data.answer.includes(marker)
			);

			const assistantMsg: ChatMessage = {
				id: generateId(),
				role: 'assistant',
				content: data.answer,
				references: data.references,
				model_used: data.model_used,
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

	async function sendMessage(question: string, filterLaw?: string | null) {
		const trimmed = question.trim();
		if (!trimmed) return;

		// Add user message
		const userMsg: ChatMessage = {
			id: generateId(),
			role: 'user',
			content: trimmed,
			timestamp: Date.now()
		};

		// Capture current messages for history before adding user message
		let currentMessages: ChatMessage[] = [];
		update((s) => {
			currentMessages = s.messages;
			return {
				...s,
				messages: [...s.messages, userMsg],
				status: 'loading',
				error: null
			};
		});

		const history = buildHistory([...currentMessages, userMsg]);

		// Try streaming first, fall back to non-streaming
		const streamed = await tryStreaming(trimmed, filterLaw, history);
		if (!streamed) {
			await fallbackAsk(trimmed, filterLaw);
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
	$chat.status === 'loading' || $chat.status === 'slow' || $chat.status === 'streaming'
);
