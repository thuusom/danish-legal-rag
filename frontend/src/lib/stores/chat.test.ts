import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';

// Mock the openapi-fetch client before importing the store
vi.mock('$lib/api/client', () => {
	const mockPost = vi.fn();
	return {
		client: {
			POST: mockPost
		}
	};
});

// Must import after mock setup
const { chatStore, isInputDisabled } = await import('./chat');
const { client } = await import('$lib/api/client');
const mockPost = vi.mocked(client.POST);

/**
 * Make global.fetch reject for /ask/stream so the store falls back to
 * the non-streaming /ask path (which is mocked via openapi-fetch client).
 */
function mockStreamUnavailable() {
	vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
		const url = typeof input === 'string' ? input : (input as Request).url;
		if (url.includes('/ask/stream')) {
			return Promise.reject(new Error('stream unavailable'));
		}
		// Let other fetches through (shouldn't happen in these tests)
		return Promise.reject(new Error(`unexpected fetch: ${url}`));
	});
}

/**
 * Create a mock SSE response for /ask/stream that delivers events
 * in a single chunk, then closes.
 */
function mockStreamResponse(events: object[]) {
	const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('');
	const encoder = new TextEncoder();
	const stream = new ReadableStream<Uint8Array>({
		start(controller) {
			controller.enqueue(encoder.encode(body));
			controller.close();
		}
	});
	vi.spyOn(globalThis, 'fetch').mockResolvedValue(
		new Response(stream, {
			status: 200,
			headers: { 'Content-Type': 'text/event-stream' }
		})
	);
}

describe('chatStore', () => {
	beforeEach(() => {
		chatStore.clearConversation();
		vi.clearAllMocks();
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.restoreAllMocks();
		vi.useRealTimers();
	});

	it('starts with empty state', () => {
		const state = get(chatStore);
		expect(state.messages).toEqual([]);
		expect(state.status).toBe('idle');
		expect(state.error).toBeNull();
	});

	it('adds a user message on sendMessage', async () => {
		mockStreamResponse([
			{ type: 'chunk', data: 'Svar' },
			{ type: 'done', data: { model_used: 'mock' } }
		]);

		const promise = chatStore.sendMessage('Test?');

		// User message should be added immediately
		const state = get(chatStore);
		expect(state.messages).toHaveLength(1);
		expect(state.messages[0].role).toBe('user');
		expect(state.messages[0].content).toBe('Test?');

		await promise;
	});

	it('adds assistant message after successful streaming response', async () => {
		mockStreamResponse([
			{ type: 'chunk', data: 'Det er ' },
			{ type: 'chunk', data: 'svaret.' },
			{
				type: 'references',
				data: [
					{
						law: 'Afskrivningsloven',
						law_code: 'AFL',
						section: '§ 41',
						quote: 'Udgifter til...',
						citation_label: 'Afskrivningsloven § 41',
						score: 0.95
					}
				]
			},
			{ type: 'done', data: { model_used: 'mock' } }
		]);

		await chatStore.sendMessage('Spørgsmål?');

		const state = get(chatStore);
		expect(state.messages).toHaveLength(2);
		expect(state.messages[1].role).toBe('assistant');
		expect(state.messages[1].content).toBe('Det er svaret.');
		expect(state.messages[1].references).toHaveLength(1);
		expect(state.messages[1].streaming).toBe(false);
		expect(state.status).toBe('idle');
	});

	it('falls back to /ask when /ask/stream is unavailable', async () => {
		mockStreamUnavailable();
		mockPost.mockResolvedValueOnce({
			data: {
				answer: 'Fallback svar',
				references: [],
				retrieved_context: [],
				question: 'Test?',
				model_used: 'mock'
			},
			error: undefined,
			response: new Response()
		} as never);

		await chatStore.sendMessage('Test?');

		const state = get(chatStore);
		expect(state.messages).toHaveLength(2);
		expect(state.messages[1].content).toBe('Fallback svar');
		expect(state.status).toBe('idle');
	});

	it('sets error status on API error (fallback path)', async () => {
		mockStreamUnavailable();
		mockPost.mockResolvedValueOnce({
			data: undefined,
			error: { detail: 'Intern serverfejl' },
			response: new Response(null, { status: 500 })
		} as never);

		await chatStore.sendMessage('Fejl?');

		const state = get(chatStore);
		expect(state.status).toBe('error');
		expect(state.error).toBe('Intern serverfejl');
		expect(state.messages).toHaveLength(1);
	});

	it('sets error on network failure (fallback path)', async () => {
		mockStreamUnavailable();
		mockPost.mockRejectedValueOnce(new Error('fetch failed'));

		await chatStore.sendMessage('Netværk?');

		const state = get(chatStore);
		expect(state.status).toBe('error');
		expect(state.error).toContain('Kunne ikke forbinde');
	});

	it('handles stream error event', async () => {
		mockStreamResponse([
			{ type: 'chunk', data: 'Delvist svar' },
			{ type: 'error', data: { detail: 'LLM timeout' } }
		]);

		await chatStore.sendMessage('Fejl under streaming?');

		const state = get(chatStore);
		expect(state.status).toBe('error');
		expect(state.error).toBe('LLM timeout');
		// User message + incomplete assistant message
		expect(state.messages).toHaveLength(2);
		expect(state.messages[1].streaming).toBe(false);
	});

	it('transitions to slow status after 5 seconds (fallback path)', async () => {
		mockStreamUnavailable();

		let resolvePost!: (value: unknown) => void;
		mockPost.mockReturnValueOnce(
			new Promise((resolve) => {
				resolvePost = resolve;
			}) as never
		);

		const promise = chatStore.sendMessage('Langsomt?');

		// Wait for the stream attempt to fail and fallback to start
		await vi.advanceTimersByTimeAsync(100);

		expect(get(chatStore).status).toBe('loading');

		// Advance time by 5 seconds for slow timer
		vi.advanceTimersByTime(5000);

		expect(get(chatStore).status).toBe('slow');

		// Resolve to clean up
		resolvePost({
			data: {
				answer: 'Svar',
				references: [],
				retrieved_context: [],
				question: 'Langsomt?',
				model_used: 'mock'
			},
			error: undefined,
			response: new Response()
		});

		await promise;
	});

	it('detects no-sources case via streaming', async () => {
		mockStreamResponse([
			{ type: 'chunk', data: 'Jeg kunne ikke finde relevante kilder til dette.' },
			{ type: 'references', data: [] },
			{ type: 'done', data: { model_used: 'mock' } }
		]);

		await chatStore.sendMessage('Noget?');

		const state = get(chatStore);
		expect(state.status).toBe('no-sources');
	});

	it('clears conversation', async () => {
		mockStreamResponse([
			{ type: 'chunk', data: 'Svar' },
			{ type: 'done', data: { model_used: 'mock' } }
		]);

		await chatStore.sendMessage('Test?');
		expect(get(chatStore).messages).toHaveLength(2);

		chatStore.clearConversation();
		const state = get(chatStore);
		expect(state.messages).toEqual([]);
		expect(state.status).toBe('idle');
		expect(state.error).toBeNull();
	});

	it('ignores empty messages', async () => {
		await chatStore.sendMessage('   ');
		expect(get(chatStore).messages).toEqual([]);
	});

	it('disables input during streaming', async () => {
		// Use a stream that we can control timing on
		let closeStream!: () => void;
		const stream = new ReadableStream<Uint8Array>({
			start(controller) {
				const encoder = new TextEncoder();
				controller.enqueue(
					encoder.encode('data: {"type":"chunk","data":"Hello"}\n\n')
				);
				closeStream = () => {
					controller.enqueue(
						encoder.encode(
							'data: {"type":"done","data":{"model_used":"mock"}}\n\n'
						)
					);
					controller.close();
				};
			}
		});
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(stream, {
				status: 200,
				headers: { 'Content-Type': 'text/event-stream' }
			})
		);

		const promise = chatStore.sendMessage('Test?');

		// Allow the stream to start reading
		await vi.advanceTimersByTimeAsync(10);

		expect(get(isInputDisabled)).toBe(true);

		closeStream();
		await promise;

		expect(get(isInputDisabled)).toBe(false);
	});

	it('sends conversation history for multi-turn context', async () => {
		// Capture all fetch calls
		const fetchCalls: { url: string; body: string }[] = [];
		let callCount = 0;

		const responses = [
			[
				{ type: 'chunk', data: 'Første svar' },
				{ type: 'done', data: { model_used: 'mock' } }
			],
			[
				{ type: 'chunk', data: 'Andet svar' },
				{ type: 'done', data: { model_used: 'mock' } }
			]
		];

		vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
			const url = typeof input === 'string' ? input : (input as Request).url;
			fetchCalls.push({ url, body: init?.body as string });

			const events = responses[callCount++];
			const sseBody = events!
				.map((e: object) => `data: ${JSON.stringify(e)}\n\n`)
				.join('');
			const encoder = new TextEncoder();
			const stream = new ReadableStream<Uint8Array>({
				start(controller) {
					controller.enqueue(encoder.encode(sseBody));
					controller.close();
				}
			});
			return Promise.resolve(
				new Response(stream, {
					status: 200,
					headers: { 'Content-Type': 'text/event-stream' }
				})
			);
		});

		await chatStore.sendMessage('Første spørgsmål');
		await chatStore.sendMessage('Opfølgning');

		// Check the second fetch call includes history
		expect(fetchCalls).toHaveLength(2);
		const body = JSON.parse(fetchCalls[1].body);
		expect(body.history).toBeDefined();
		expect(body.history).toHaveLength(3); // user1 + assistant1 + user2
		expect(body.history[0].role).toBe('user');
		expect(body.history[0].content).toBe('Første spørgsmål');
		expect(body.history[1].role).toBe('assistant');
		expect(body.history[2].role).toBe('user');
		expect(body.history[2].content).toBe('Opfølgning');
	});
});
