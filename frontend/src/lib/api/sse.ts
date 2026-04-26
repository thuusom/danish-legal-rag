import type { components } from './schema';

type StreamChunkEvent = components['schemas']['StreamChunkEvent'];
type StreamReferencesEvent = components['schemas']['StreamReferencesEvent'];
type StreamDoneEvent = components['schemas']['StreamDoneEvent'];
type StreamErrorEvent = components['schemas']['StreamErrorEvent'];

export type StreamEvent =
	| StreamChunkEvent
	| StreamReferencesEvent
	| StreamDoneEvent
	| StreamErrorEvent;

/**
 * Parse a single SSE data line into a typed event.
 * Expects the raw content after the "data: " prefix.
 */
export function parseSSEEvent(jsonStr: string): StreamEvent | null {
	try {
		const parsed: unknown = JSON.parse(jsonStr);
		if (typeof parsed !== 'object' || parsed === null || !('type' in parsed)) {
			return null;
		}
		return parsed as StreamEvent;
	} catch {
		return null;
	}
}

export interface StreamCallbacks {
	onChunk: (data: string) => void;
	onReferences: (refs: StreamReferencesEvent['data']) => void;
	onDone: (data: StreamDoneEvent['data']) => void;
	onError: (detail: string) => void;
}

/**
 * Consume an SSE response body from a POST /ask/stream request.
 * Parses "data: {json}\n\n" frames and dispatches to callbacks.
 *
 * Returns when the stream closes or a done/error event arrives.
 */
export async function consumeSSEStream(
	response: Response,
	callbacks: StreamCallbacks
): Promise<void> {
	const reader = response.body!.getReader();
	const decoder = new TextDecoder();
	let buffer = '';

	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;

			buffer += decoder.decode(value, { stream: true });

			// Split on double-newline (SSE frame boundary)
			const frames = buffer.split('\n\n');
			// Last element is incomplete — keep it in the buffer
			buffer = frames.pop() ?? '';

			for (const frame of frames) {
				const trimmed = frame.trim();
				if (!trimmed) continue;

				// Each frame can have multiple lines; find the "data: " line
				for (const line of trimmed.split('\n')) {
					if (line.startsWith('data: ')) {
						const jsonStr = line.slice(6);
						const event = parseSSEEvent(jsonStr);
						if (!event) continue;

						switch (event.type) {
							case 'chunk':
								callbacks.onChunk(event.data);
								break;
							case 'references':
								callbacks.onReferences(event.data);
								break;
							case 'done':
								callbacks.onDone(event.data);
								return;
							case 'error':
								callbacks.onError(event.data.detail);
								return;
						}
					}
				}
			}
		}
	} finally {
		reader.releaseLock();
	}
}
