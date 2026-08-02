<script lang="ts">
	import type { EvalRunConfig } from '$lib/api/evals';
	import { diffConfigs, getDiffCellClasses } from '$lib/utils/diff';

	interface Props {
		/** One entry per selected run, baseline first. */
		configs: (EvalRunConfig | null | undefined)[];
		labels: string[];
		showUnchanged?: boolean;
	}

	let { configs, labels, showUnchanged = true }: Props = $props();

	let rows = $derived(diffConfigs(configs));
	let visibleRows = $derived(showUnchanged ? rows : rows.filter((r) => r.varies));
	let hasChanges = $derived(rows.some((r) => r.varies));
</script>

<div class="term-panel">
	<div class="flex items-center gap-2 mb-2 text-xs text-base-content/70 flex-wrap">
		<span class="term-label">Config</span>
		{#each labels as label, i}
			{#if i > 0}<span class="text-base-content/30">·</span>{/if}
			<span class="badge badge-ghost badge-sm">{label}</span>
		{/each}
		{#if configs.length >= 2 && !hasChanges}
			<span class="badge badge-success badge-sm ml-auto">Identical</span>
		{/if}
	</div>

	{#if configs.length === 0 || rows.length === 0}
		<div class="text-center py-4 text-base-content/50 text-xs">
			Select at least two runs to compare configurations
		</div>
	{:else}
		<div class="overflow-x-auto">
			<table class="table table-xs term-table font-mono">
				<thead>
					<tr>
						<th>Setting</th>
						{#each labels as label, i}
							<th class="text-right">
								{label}
								{#if i === 0}<div class="text-[10px] font-normal text-base-content/40 normal-case">baseline</div>{/if}
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each visibleRows as row}
						<tr class="hover">
							<td class="font-semibold">{row.key}</td>
							{#each row.cells as cell}
								<td class="text-right">
									<span class="px-1 rounded-sm {getDiffCellClasses(cell)}">
										{#if cell.changed}<span class="opacity-60 mr-0.5" aria-label="differs from baseline">~</span>{/if}
										{cell.value}
									</span>
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		{#if !showUnchanged && rows.length > visibleRows.length}
			<div class="text-center py-1 text-base-content/50 text-xs mt-2">
				{rows.length - visibleRows.length} unchanged setting{rows.length - visibleRows.length === 1 ? '' : 's'} hidden
			</div>
		{/if}
	{/if}
</div>
