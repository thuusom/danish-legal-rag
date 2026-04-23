import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

// Mock localStorage
const localStorageMock = (() => {
	let store: Record<string, string> = {};
	return {
		getItem: vi.fn((key: string) => store[key] ?? null),
		setItem: vi.fn((key: string, value: string) => {
			store[key] = value;
		}),
		removeItem: vi.fn((key: string) => {
			delete store[key];
		}),
		clear: vi.fn(() => {
			store = {};
		}),
		get length() {
			return Object.keys(store).length;
		},
		key: vi.fn((_index: number) => null)
	};
})();

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock });

// Mock crypto.randomUUID
let uuidCounter = 0;
vi.stubGlobal('crypto', {
	randomUUID: () => `test-uuid-${++uuidCounter}`
});

describe('sessionStore', () => {
	beforeEach(async () => {
		localStorageMock.clear();
		vi.clearAllMocks();
		uuidCounter = 0;

		// Re-import to get a fresh store each time
		vi.resetModules();
	});

	async function getStore() {
		const mod = await import('./sessions');
		return mod.sessionStore;
	}

	it('starts with empty sessions', async () => {
		const store = await getStore();
		expect(get(store.sessions)).toEqual([]);
		expect(get(store.activeSessionId)).toBeNull();
	});

	it('creates a new session', async () => {
		const store = await getStore();
		const id = store.createSession();

		expect(id).toBe('test-uuid-1');
		const sessions = get(store.sessions);
		expect(sessions).toHaveLength(1);
		expect(sessions[0].id).toBe('test-uuid-1');
		expect(sessions[0].title).toBe('Ny samtale');
		expect(sessions[0].messages).toEqual([]);
		expect(get(store.activeSessionId)).toBe('test-uuid-1');
	});

	it('updates the current session with messages', async () => {
		const store = await getStore();
		store.createSession();

		const messages = [
			{
				id: 'msg-1',
				role: 'user' as const,
				content: 'Hvad er afskrivningsloven?',
				timestamp: Date.now()
			},
			{
				id: 'msg-2',
				role: 'assistant' as const,
				content: 'Afskrivningsloven handler om...',
				timestamp: Date.now()
			}
		];

		store.updateCurrentSession(messages);

		const sessions = get(store.sessions);
		expect(sessions[0].messages).toEqual(messages);
		expect(sessions[0].title).toBe('Hvad er afskrivningsloven?');
	});

	it('truncates title to ~50 characters', async () => {
		const store = await getStore();
		store.createSession();

		const longQuestion =
			'Hvad er reglerne for skattemæssig afskrivning af driftsmidler og inventar i en virksomhed?';
		const messages = [
			{
				id: 'msg-1',
				role: 'user' as const,
				content: longQuestion,
				timestamp: Date.now()
			}
		];

		store.updateCurrentSession(messages);

		const sessions = get(store.sessions);
		expect(sessions[0].title.length).toBeLessThanOrEqual(53); // 50 + "..."
		expect(sessions[0].title).toMatch(/\.\.\.$/);
	});

	it('creates a session automatically when updating without active session', async () => {
		const store = await getStore();

		const messages = [
			{
				id: 'msg-1',
				role: 'user' as const,
				content: 'Test spørgsmål',
				timestamp: Date.now()
			}
		];

		store.updateCurrentSession(messages);

		const sessions = get(store.sessions);
		expect(sessions).toHaveLength(1);
		expect(sessions[0].messages).toEqual(messages);
	});

	it('loads a session by ID', async () => {
		const store = await getStore();
		store.createSession();

		const messages = [
			{
				id: 'msg-1',
				role: 'user' as const,
				content: 'Spørgsmål 1',
				timestamp: Date.now()
			}
		];
		store.updateCurrentSession(messages);

		// Create second session
		const id2 = store.createSession();
		expect(get(store.activeSessionId)).toBe(id2);

		// Load the first session
		const loaded = store.loadSession('test-uuid-1');
		expect(loaded).toEqual(messages);
		expect(get(store.activeSessionId)).toBe('test-uuid-1');
	});

	it('returns null when loading a non-existent session', async () => {
		const store = await getStore();
		const result = store.loadSession('non-existent');
		expect(result).toBeNull();
	});

	it('deletes a session', async () => {
		const store = await getStore();
		const id = store.createSession();

		expect(get(store.sessions)).toHaveLength(1);

		store.deleteSession(id);

		expect(get(store.sessions)).toHaveLength(0);
		expect(get(store.activeSessionId)).toBeNull();
	});

	it('clears activeSessionId when deleting the active session', async () => {
		const store = await getStore();
		const id1 = store.createSession();
		store.createSession(); // id2 is now active

		// Delete active session (id2)
		store.deleteSession(get(store.activeSessionId)!);

		// Active should be cleared since deleted session was active
		expect(get(store.activeSessionId)).toBeNull();

		// id1 should still exist
		expect(get(store.sessions)).toHaveLength(1);
		expect(get(store.sessions)[0].id).toBe(id1);
	});

	it('persists sessions to localStorage', async () => {
		const store = await getStore();
		store.createSession();

		// Check that localStorage was written
		expect(localStorageMock.setItem).toHaveBeenCalledWith(
			'danish-legal-rag-sessions',
			expect.any(String)
		);

		const stored = localStorageMock.getItem('danish-legal-rag-sessions');
		expect(stored).not.toBeNull();
		const parsed = JSON.parse(stored!);
		expect(parsed).toHaveLength(1);
	});

	it('restores sessions from localStorage on init', async () => {
		const existingSessions = [
			{
				id: 'restored-1',
				title: 'Gammel samtale',
				messages: [
					{
						id: 'msg-old',
						role: 'user',
						content: 'Et gammelt spørgsmål',
						timestamp: 1000
					}
				],
				timestamp: 1000
			}
		];
		localStorageMock.setItem(
			'danish-legal-rag-sessions',
			JSON.stringify(existingSessions)
		);
		localStorageMock.setItem('danish-legal-rag-active-session', 'restored-1');

		const store = await getStore();
		const sessions = get(store.sessions);
		expect(sessions).toHaveLength(1);
		expect(sessions[0].id).toBe('restored-1');
		expect(get(store.activeSessionId)).toBe('restored-1');
	});

	it('handles multiple sessions and switching', async () => {
		const store = await getStore();

		// Create first session with messages
		store.createSession();
		store.updateCurrentSession([
			{ id: 'a1', role: 'user', content: 'Første spørgsmål', timestamp: 1 }
		]);

		// Create second session with messages
		store.createSession();
		store.updateCurrentSession([
			{ id: 'b1', role: 'user', content: 'Andet spørgsmål', timestamp: 2 }
		]);

		expect(get(store.sessions)).toHaveLength(2);

		// Switch back to first session
		const firstMessages = store.loadSession('test-uuid-1');
		expect(firstMessages).toHaveLength(1);
		expect(firstMessages![0].content).toBe('Første spørgsmål');

		// Switch to second session
		const secondMessages = store.loadSession('test-uuid-2');
		expect(secondMessages).toHaveLength(1);
		expect(secondMessages![0].content).toBe('Andet spørgsmål');
	});

	it('getActiveSessionId returns current active ID', async () => {
		const store = await getStore();
		expect(store.getActiveSessionId()).toBeNull();

		const id = store.createSession();
		expect(store.getActiveSessionId()).toBe(id);
	});
});
