import { writable } from 'svelte/store';
import { generateId } from '$lib/utils/id';

export type ToastKind = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
	id: string;
	kind: ToastKind;
	message: string;
}

function createToastStore() {
	const { subscribe, update } = writable<Toast[]>([]);

	function show(message: string, kind: ToastKind = 'info', durationMs = 4000): string {
		const id = generateId();
		update((toasts) => [...toasts, { id, kind, message }]);
		if (durationMs > 0 && typeof window !== 'undefined') {
			window.setTimeout(() => dismiss(id), durationMs);
		}
		return id;
	}

	function dismiss(id: string) {
		update((toasts) => toasts.filter((t) => t.id !== id));
	}

	function clear() {
		update(() => []);
	}

	return {
		subscribe,
		show,
		dismiss,
		clear,
		info: (m: string, d?: number) => show(m, 'info', d),
		success: (m: string, d?: number) => show(m, 'success', d),
		warning: (m: string, d?: number) => show(m, 'warning', d),
		error: (m: string, d?: number) => show(m, 'error', d)
	};
}

export const toastStore = createToastStore();
