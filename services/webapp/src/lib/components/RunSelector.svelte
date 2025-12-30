<script lang="ts">
	import type { EvaluationRun } from '$lib/api';

	interface Props {
		runs: EvaluationRun[];
		selected: string[];
		onSelectionChange: (ids: string[]) => void;
		maxSelection?: number;
	}

	let { runs, selected, onSelectionChange, maxSelection = 8 }: Props = $props();

	function toggleRun(runId: string) {
		if (selected.includes(runId)) {
			onSelectionChange(selected.filter((id) => id !== runId));
		} else if (selected.length < maxSelection) {
			onSelectionChange([...selected, runId]);
		}
	}

	function selectAll() {
		const toSelect = runs.slice(0, maxSelection).map((r) => r.run_id);
		onSelectionChange(toSelect);
	}

	function clearAll() {
		onSelectionChange([]);
	}

	function getRunLabel(run: EvaluationRun): string {
		const model = run.config_snapshot?.llm_model || 'Unknown';
		return model;
	}

	function getRunTime(run: EvaluationRun): string {
		return new Date(run.timestamp).toLocaleTimeString('en-US', {
			hour: '2-digit',
			minute: '2-digit',
			hour12: false
		});
	}

	function getRunDate(run: EvaluationRun): string {
		return new Date(run.timestamp).toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric'
		});
	}

	function timeAgo(timestamp: string): string {
		const diff = Date.now() - new Date(timestamp).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		const days = Math.floor(hours / 24);
		return `${days}d ago`;
	}

	function getPassRateColor(rate: number): string {
		if (rate >= 0.8) return 'badge-success';
		if (rate >= 0.6) return 'badge-warning';
		return 'badge-error';
	}
</script>

<div class="bg-base-200 rounded p-2">
	<div class="flex items-center justify-between mb-2">
		<span class="text-xs font-semibold text-base-content/70">
			Select Runs ({selected.length}/{maxSelection})
		</span>
		<div class="flex gap-1">
			<button
				class="btn btn-xs btn-ghost"
				onclick={selectAll}
				disabled={runs.length === 0 || selected.length === Math.min(runs.length, maxSelection)}
			>
				All
			</button>
			<button class="btn btn-xs btn-ghost" onclick={clearAll} disabled={selected.length === 0}>
				Clear
			</button>
		</div>
	</div>

	{#if runs.length === 0}
		<div class="text-center py-4 text-base-content/50 text-xs">
			No evaluation runs available
		</div>
	{:else}
		<div class="max-h-56 overflow-y-auto space-y-1">
			{#each runs as run}
				{@const isSelected = selected.includes(run.run_id)}
				{@const isDisabled = !isSelected && selected.length >= maxSelection}
				<label
					class="flex items-center gap-2 p-1.5 rounded cursor-pointer text-xs
						{isSelected ? 'bg-primary/10' : 'hover:bg-base-300'}
						{isDisabled ? 'opacity-50 cursor-not-allowed' : ''}"
				>
					<input
						type="checkbox"
						class="checkbox checkbox-xs checkbox-primary"
						checked={isSelected}
						disabled={isDisabled}
						onchange={() => toggleRun(run.run_id)}
					/>
					<div class="flex-1 min-w-0">
						<div class="font-mono truncate" title={getRunLabel(run)}>
							{getRunLabel(run)}
						</div>
						<div class="text-base-content/50 flex items-center gap-2">
							<span>{getRunDate(run)} {getRunTime(run)}</span>
							<span class="badge badge-xs {getPassRateColor(run.pass_rate)}">
								{(run.pass_rate * 100).toFixed(0)}%
							</span>
						</div>
					</div>
					<div class="text-base-content/40 text-right whitespace-nowrap">
						{timeAgo(run.timestamp)}
					</div>
					{#if run.is_golden_baseline}
						<span class="badge badge-xs badge-warning">baseline</span>
					{/if}
				</label>
			{/each}
		</div>
	{/if}
</div>
