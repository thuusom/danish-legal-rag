import { writable, get } from 'svelte/store';
import type { ChatMessage } from './chat';
import { generateId } from '$lib/utils/id';

export interface Session {
	id: string;
	title: string;
	messages: ChatMessage[];
	timestamp: number;
}

const STORAGE_KEY = 'danish-legal-rag-sessions';
const ACTIVE_SESSION_KEY = 'danish-legal-rag-active-session';
const MAX_TITLE_LENGTH = 50;

/**
 * Read sessions from localStorage. Returns empty array on failure.
 */
function loadSessions(): Session[] {
	if (typeof localStorage === 'undefined') return [];
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return [];
		const parsed: unknown = JSON.parse(raw);
		if (!Array.isArray(parsed)) return [];
		return parsed as Session[];
	} catch {
		return [];
	}
}

/**
 * Read the active session ID from localStorage.
 */
function loadActiveSessionId(): string | null {
	if (typeof localStorage === 'undefined') return null;
	try {
		return localStorage.getItem(ACTIVE_SESSION_KEY);
	} catch {
		return null;
	}
}

/**
 * Persist sessions to localStorage.
 */
function saveSessions(sessions: Session[]): void {
	if (typeof localStorage === 'undefined') return;
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
	} catch {
		// Storage full or unavailable -- silently ignore for now
	}
}

/**
 * Persist the active session ID to localStorage.
 */
function saveActiveSessionId(id: string | null): void {
	if (typeof localStorage === 'undefined') return;
	try {
		if (id) {
			localStorage.setItem(ACTIVE_SESSION_KEY, id);
		} else {
			localStorage.removeItem(ACTIVE_SESSION_KEY);
		}
	} catch {
		// Silently ignore
	}
}

/**
 * Derive a session title from the first user message, truncated.
 */
function deriveTitle(messages: ChatMessage[]): string {
	const firstUser = messages.find((m) => m.role === 'user');
	if (!firstUser) return 'Ny samtale';
	const text = firstUser.content.trim();
	if (text.length <= MAX_TITLE_LENGTH) return text;
	return text.slice(0, MAX_TITLE_LENGTH) + '...';
}

function createSessionStore() {
	const sessions = writable<Session[]>(loadSessions());
	const activeSessionId = writable<string | null>(loadActiveSessionId());

	// Persist whenever sessions change
	sessions.subscribe((value) => saveSessions(value));
	activeSessionId.subscribe((value) => saveActiveSessionId(value));

	/**
	 * Create a new empty session and set it as active.
	 * Returns the new session ID.
	 */
	function createSession(): string {
		const id = generateId();
		const session: Session = {
			id,
			title: 'Ny samtale',
			messages: [],
			timestamp: Date.now()
		};
		sessions.update((s) => [session, ...s]);
		activeSessionId.set(id);
		return id;
	}

	/**
	 * Update the current active session with new messages.
	 * Creates a session if none is active.
	 */
	function updateCurrentSession(messages: ChatMessage[]): void {
		let currentId = get(activeSessionId);

		if (!currentId) {
			currentId = createSession();
		}

		sessions.update((allSessions) =>
			allSessions.map((s) => {
				if (s.id === currentId) {
					return {
						...s,
						messages,
						title: deriveTitle(messages),
						timestamp: Date.now()
					};
				}
				return s;
			})
		);
	}

	/**
	 * Load a session by ID. Returns its messages, or null if not found.
	 */
	function loadSession(id: string): ChatMessage[] | null {
		const allSessions = get(sessions);
		const session = allSessions.find((s) => s.id === id);
		if (!session) return null;
		activeSessionId.set(id);
		return session.messages;
	}

	/**
	 * Delete a session by ID. If it was the active session, clears active.
	 */
	function deleteSession(id: string): void {
		sessions.update((s) => s.filter((session) => session.id !== id));
		if (get(activeSessionId) === id) {
			activeSessionId.set(null);
		}
	}

	/**
	 * Get the active session ID.
	 */
	function getActiveSessionId(): string | null {
		return get(activeSessionId);
	}

	return {
		sessions,
		activeSessionId,
		createSession,
		updateCurrentSession,
		loadSession,
		deleteSession,
		getActiveSessionId
	};
}

export const sessionStore = createSessionStore();
