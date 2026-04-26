/**
 * Generate a unique ID string.
 *
 * Prefers `crypto.randomUUID()` when available (secure contexts: HTTPS or
 * localhost). Falls back to `crypto.getRandomValues()` which works in ALL
 * contexts, including plain HTTP on LAN IPs like http://10.0.0.3.
 *
 * This avoids the silent throw that kills `sendMessage` when users access
 * the app over a non-localhost HTTP connection.
 */
export function generateId(): string {
	try {
		return crypto.randomUUID();
	} catch {
		// Insecure context (non-localhost HTTP) — randomUUID is unavailable.
		// Build a v4-style UUID from getRandomValues, which works everywhere.
		const bytes = new Uint8Array(16);
		crypto.getRandomValues(bytes);
		// Set version (4) and variant (RFC 4122) bits
		bytes[6] = (bytes[6] & 0x0f) | 0x40;
		bytes[8] = (bytes[8] & 0x3f) | 0x80;
		const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
		return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
	}
}
