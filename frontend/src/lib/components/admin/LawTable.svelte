<script lang="ts">
	import type { components } from '$lib/api/schema';

	type AdminLawStatus = components['schemas']['AdminLawStatus'];
	type LawStatus = AdminLawStatus['status'];

	interface Props {
		laws: AdminLawStatus[];
		loading: boolean;
	}

	let { laws, loading }: Props = $props();

	type SortKey = 'law_code' | 'law_name' | 'our_version' | 'our_version_date' | 'status';
	type SortDir = 'asc' | 'desc';

	let sortKey = $state<SortKey>('law_code');
	let sortDir = $state<SortDir>('asc');

	const sortedLaws = $derived.by(() => {
		const arr = [...laws];
		const dir = sortDir === 'asc' ? 1 : -1;
		arr.sort((a, b) => {
			const av = (a[sortKey] ?? '') as string | number;
			const bv = (b[sortKey] ?? '') as string | number;
			if (av < bv) return -1 * dir;
			if (av > bv) return 1 * dir;
			return 0;
		});
		return arr;
	});

	function toggleSort(key: SortKey) {
		if (sortKey === key) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		} else {
			sortKey = key;
			sortDir = 'asc';
		}
	}

	function statusLabel(s: LawStatus): string {
		switch (s) {
			case 'ok':
				return 'Aktuel';
			case 'outdated':
				return 'Forældet';
			case 'fetch-failed':
				return 'Hentningsfejl';
			default:
				return 'Ukendt';
		}
	}

	function statusPillClass(s: LawStatus): string {
		switch (s) {
			case 'ok':
				return 'bg-green-100 text-green-800';
			case 'outdated':
				return 'bg-amber-100 text-amber-800';
			case 'fetch-failed':
				return 'bg-red-100 text-red-800';
			default:
				return 'bg-gray-100 text-gray-700';
		}
	}

	function formatDate(value: string | null | undefined): string {
		if (!value) return '—';
		try {
			// `value` is a YYYY-MM-DD string; show as-is for predictability.
			return value;
		} catch {
			return value ?? '—';
		}
	}

	function formatVersion(law: AdminLawStatus): string {
		if (law.our_version_number != null) return `v${law.our_version_number}`;
		if (law.our_version) return law.our_version;
		return '—';
	}

	function ariaSort(key: SortKey): 'ascending' | 'descending' | 'none' {
		if (sortKey !== key) return 'none';
		return sortDir === 'asc' ? 'ascending' : 'descending';
	}
</script>

<div
	class="overflow-x-auto rounded-lg border border-gray-200 bg-white"
	data-testid="admin-law-table-wrapper"
>
	<table class="min-w-full divide-y divide-gray-200 text-sm" data-testid="admin-law-table">
		<thead class="bg-gray-50">
			<tr>
				<th
					scope="col"
					class="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-600 uppercase"
					aria-sort={ariaSort('law_code')}
				>
					<button
						type="button"
						onclick={() => toggleSort('law_code')}
						class="flex items-center gap-1 hover:text-gray-900"
					>
						Lov
						<span aria-hidden="true">
							{sortKey === 'law_code' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
						</span>
					</button>
				</th>
				<th
					scope="col"
					class="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-600 uppercase"
					aria-sort={ariaSort('law_name')}
				>
					<button
						type="button"
						onclick={() => toggleSort('law_name')}
						class="flex items-center gap-1 hover:text-gray-900"
					>
						Navn
						<span aria-hidden="true">
							{sortKey === 'law_name' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
						</span>
					</button>
				</th>
				<th
					scope="col"
					class="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-600 uppercase"
					aria-sort={ariaSort('our_version')}
				>
					<button
						type="button"
						onclick={() => toggleSort('our_version')}
						class="flex items-center gap-1 hover:text-gray-900"
					>
						Version
						<span aria-hidden="true">
							{sortKey === 'our_version' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
						</span>
					</button>
				</th>
				<th
					scope="col"
					class="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-600 uppercase"
					aria-sort={ariaSort('our_version_date')}
				>
					<button
						type="button"
						onclick={() => toggleSort('our_version_date')}
						class="flex items-center gap-1 hover:text-gray-900"
					>
						Snapshot
						<span aria-hidden="true">
							{sortKey === 'our_version_date' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
						</span>
					</button>
				</th>
				<th
					scope="col"
					class="hidden px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-600 uppercase md:table-cell"
				>
					Seneste version
				</th>
				<th
					scope="col"
					class="hidden px-3 py-2 text-right text-xs font-semibold tracking-wide text-gray-600 uppercase md:table-cell"
				>
					Bestemmelser
				</th>
				<th
					scope="col"
					class="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-600 uppercase"
					aria-sort={ariaSort('status')}
				>
					<button
						type="button"
						onclick={() => toggleSort('status')}
						class="flex items-center gap-1 hover:text-gray-900"
					>
						Status
						<span aria-hidden="true">
							{sortKey === 'status' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
						</span>
					</button>
				</th>
			</tr>
		</thead>
		<tbody class="divide-y divide-gray-100 bg-white">
			{#if loading}
				<tr>
					<td colspan="7" class="px-3 py-6 text-center text-gray-400" data-testid="loading-row">
						Indlæser love…
					</td>
				</tr>
			{:else if sortedLaws.length === 0}
				<tr>
					<td colspan="7" class="px-3 py-6 text-center text-gray-400" data-testid="empty-row">
						Ingen love konfigureret.
					</td>
				</tr>
			{:else}
				{#each sortedLaws as law (law.law_code)}
					<tr data-testid="law-row" data-law-code={law.law_code}>
						<td class="px-3 py-2 font-mono text-xs text-gray-700">{law.law_code}</td>
						<td class="px-3 py-2 text-gray-800">
							<div class="font-medium">{law.law_name}</div>
							{#if law.law_title}
								<div class="text-xs text-gray-500">{law.law_title}</div>
							{/if}
						</td>
						<td class="px-3 py-2 text-gray-700">{formatVersion(law)}</td>
						<td class="px-3 py-2 text-gray-700">{formatDate(law.our_version_date)}</td>
						<td class="hidden px-3 py-2 text-gray-700 md:table-cell">
							{#if law.latest_version_number != null}
								v{law.latest_version_number}
								<span class="text-xs text-gray-500">
									{law.latest_version_date ? `(${law.latest_version_date})` : ''}
								</span>
							{:else}
								—
							{/if}
						</td>
						<td class="hidden px-3 py-2 text-right tabular-nums text-gray-700 md:table-cell">
							{law.provisions_count ?? '—'}
						</td>
						<td class="px-3 py-2">
							<span
								class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {statusPillClass(
									law.status
								)}"
								data-testid="status-pill"
								data-status={law.status}
								title={law.status === 'fetch-failed' && law.fetch_error
									? law.fetch_error
									: undefined}
							>
								{statusLabel(law.status)}
							</span>
							{#if law.status === 'fetch-failed' && law.fetch_error}
								<p class="mt-1 max-w-xs truncate text-xs text-red-700" title={law.fetch_error}>
									{law.fetch_error}
								</p>
							{/if}
						</td>
					</tr>
				{/each}
			{/if}
		</tbody>
	</table>
</div>
