import { describe, it, expect, vi } from 'vitest';
import { parseSSEEvent, consumeSSEStream, type StreamCallbacks } from './sse';

describe('parseSSEEvent', () => {
	it('parses a chunk event', () => {
		const event = parseSSEEvent('{"type":"chunk","data":"Hello"}');
		expect(event).toEqual({ type: 'chunk', data: 'Hello' });
	});

	it('parses a references event', () => {
		const event = parseSSEEvent(
			'{"type":"references","data":[{"law":"Test","law_code":"T","section":"§ 1","quote":"text","citation_label":"Test § 1"}]}'
		);
		expect(event).not.toBeNull();
		expect(event!.type).toBe('references');
	});

	it('parses a done event', () => {
		const event = parseSSEEvent('{"type":"done","data":{"model_used":"test-model"}}');
		expect(event).toEqual({ type: 'done', data: { model_used: 'test-model' } });
	});

	it('parses an error event', () => {
		const event = parseSSEEvent('{"type":"error","data":{"detail":"Something went wrong"}}');
		expect(event).toEqual({
			type: 'error',
			data: { detail: 'Something went wrong' }
		});
	});

	it('returns null for invalid JSON', () => {
		expect(parseSSEEvent('not json')).toBeNull();
	});

	it('returns null for object without type field', () => {
		expect(parseSSEEvent('{"data":"hello"}')).toBeNull();
	});

	it('returns null for non-object values', () => {
		expect(parseSSEEvent('"string"')).toBeNull();
		expect(parseSSEEvent('42')).toBeNull();
		expect(parseSSEEvent('null')).toBeNull();
	});
});

describe('consumeSSEStream', () => {
	function createMockResponse(frames: string[]): Response {
		// Encode all frames as a single SSE text body
		const body = frames.join('');
		const encoder = new TextEncoder();
		const stream = new ReadableStream<Uint8Array>({
			start(controller) {
				controller.enqueue(encoder.encode(body));
				controller.close();
			}
		});
		return new Response(stream);
	}

	it('dispatches chunk events', async () => {
		const callbacks: StreamCallbacks = {
			onChunk: vi.fn(),
			onReferences: vi.fn(),
			onDone: vi.fn(),
			onError: vi.fn()
		};

		const response = createMockResponse([
			'data: {"type":"chunk","data":"Hello "}\n\n',
			'data: {"type":"chunk","data":"world"}\n\n',
			'data: {"type":"done","data":{"model_used":"test"}}\n\n'
		]);

		await consumeSSEStream(response, callbacks);

		expect(callbacks.onChunk).toHaveBeenCalledTimes(2);
		expect(callbacks.onChunk).toHaveBeenNthCalledWith(1, 'Hello ');
		expect(callbacks.onChunk).toHaveBeenNthCalledWith(2, 'world');
		expect(callbacks.onDone).toHaveBeenCalledWith({ model_used: 'test' });
	});

	it('dispatches references before done', async () => {
		const callbacks: StreamCallbacks = {
			onChunk: vi.fn(),
			onReferences: vi.fn(),
			onDone: vi.fn(),
			onError: vi.fn()
		};

		const refs = [
			{
				law: 'Afskrivningsloven',
				law_code: 'AFL',
				section: '§ 41',
				quote: 'Udgifter...',
				citation_label: 'Afskrivningsloven § 41'
			}
		];

		const response = createMockResponse([
			'data: {"type":"chunk","data":"Svar"}\n\n',
			`data: {"type":"references","data":${JSON.stringify(refs)}}\n\n`,
			'data: {"type":"done","data":{"model_used":"mock"}}\n\n'
		]);

		await consumeSSEStream(response, callbacks);

		expect(callbacks.onReferences).toHaveBeenCalledWith(refs);
		expect(callbacks.onDone).toHaveBeenCalled();
	});

	it('stops on error event', async () => {
		const callbacks: StreamCallbacks = {
			onChunk: vi.fn(),
			onReferences: vi.fn(),
			onDone: vi.fn(),
			onError: vi.fn()
		};

		const response = createMockResponse([
			'data: {"type":"chunk","data":"partial"}\n\n',
			'data: {"type":"error","data":{"detail":"LLM timeout"}}\n\n',
			'data: {"type":"chunk","data":"should not arrive"}\n\n'
		]);

		await consumeSSEStream(response, callbacks);

		expect(callbacks.onChunk).toHaveBeenCalledTimes(1);
		expect(callbacks.onError).toHaveBeenCalledWith('LLM timeout');
		expect(callbacks.onDone).not.toHaveBeenCalled();
	});
});
