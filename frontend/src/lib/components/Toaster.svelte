<script lang="ts">
	import { toastStore, type ToastKind } from '$lib/stores/toast';

	function bgClass(kind: ToastKind): string {
		switch (kind) {
			case 'success':
				return 'bg-green-50 border-green-200 text-green-800';
			case 'warning':
				return 'bg-amber-50 border-amber-200 text-amber-800';
			case 'error':
				return 'bg-red-50 border-red-200 text-red-800';
			default:
				return 'bg-gray-50 border-gray-200 text-gray-800';
		}
	}
</script>

<div
	class="pointer-events-none fixed top-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
	aria-live="polite"
	aria-atomic="false"
	data-testid="toaster"
>
	{#each $toastStore as toast (toast.id)}
		<div
			class="pointer-events-auto flex items-start gap-2 rounded-md border px-3 py-2 text-sm shadow-sm {bgClass(
				toast.kind
			)}"
			role="status"
			data-testid="toast"
			data-kind={toast.kind}
		>
			<p class="flex-1">{toast.message}</p>
			<button
				onclick={() => toastStore.dismiss(toast.id)}
				class="shrink-0 rounded p-0.5 text-current opacity-60 transition-opacity hover:opacity-100"
				aria-label="Luk besked"
			>
				<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		</div>
	{/each}
</div>
