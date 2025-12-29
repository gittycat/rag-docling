<script lang="ts">
	import { compareRuns, fetchEvaluationHistory, type EvaluationRun, type ComparisonResult } from '$lib/api';

	let runs = $state<EvaluationRun[]>([]);
	let runAId = $state<string>('');
	let runBId = $state<string>('');
	let comparison = $state<ComparisonResult | null>(null);
	let isLoading = $state(false);
	let error = $state<string | null>(null);

	async function loadRuns() {
		try {
			runs = await fetchEvaluationHistory(20);
			if (runs.length >= 2) {
				runAId = runs[0].run_id;
				runBId = runs[1].run_id;
			}
		} catch (e) {
			console.error('Failed to load runs:', e);
		}
	}

	async function handleCompare() {
		if (!runAId || !runBId || runAId === runBId) return;
		isLoading = true;
		error = null;
		try {
			comparison = await compareRuns(runAId, runBId);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to compare runs';
			comparison = null;
		} finally {
			isLoading = false;
		}
	}

	function formatPercent(value: number): string {
		return `${(value * 100).toFixed(1)}%`;
	}

	function formatDelta(value: number): string {
		const sign = value > 0 ? '+' : '';
		return `${sign}${(value * 100).toFixed(1)}%`;
	}

	function getDeltaClass(value: number): string {
		if (value > 0.01) return 'text-success';
		if (value < -0.01) return 'text-error';
		return 'text-base-content/60';
	}

	function getRunLabel(run: EvaluationRun): string {
		const model = run.config_snapshot?.llm_model || 'Unknown';
		const date = new Date(run.timestamp).toLocaleDateString();
		return `${model} (${date})`;
	}

	// Load runs on mount
	$effect(() => {
		loadRuns();
	});
</script>

<div class="run-comparison bg-base-200 rounded p-3">
	<div class="text-xs font-semibold mb-2 text-base-content/70">Compare Configurations</div>

	{#if runs.length < 2}
		<div class="text-xs text-base-content/60">
			Run at least 2 evaluations to compare configurations
		</div>
	{:else}
		<!-- Run Selectors -->
		<div class="flex items-center gap-2 mb-3">
			<select
				bind:value={runAId}
				class="select select-xs select-bordered flex-1"
				onchange={() => { comparison = null; }}
			>
				{#each runs as run}
					<option value={run.run_id}>{getRunLabel(run)}</option>
				{/each}
			</select>

			<span class="text-xs text-base-content/60">vs</span>

			<select
				bind:value={runBId}
				class="select select-xs select-bordered flex-1"
				onchange={() => { comparison = null; }}
			>
				{#each runs as run}
					<option value={run.run_id}>{getRunLabel(run)}</option>
				{/each}
			</select>

			<button
				class="btn btn-xs btn-primary"
				onclick={handleCompare}
				disabled={isLoading || runAId === runBId}
			>
				{isLoading ? '...' : 'Compare'}
			</button>
		</div>

		{#if error}
			<div class="text-xs text-error">{error}</div>
		{:else if comparison}
			<!-- Comparison Results -->
			<div class="grid grid-cols-2 gap-3">
				<!-- Run A -->
				<div class="bg-base-100 rounded p-2">
					<div class="text-xs font-semibold mb-1">
						{comparison.run_a_config?.llm_model || 'Run A'}
					</div>
					{#each Object.entries(comparison.metric_deltas) as [metric, delta]}
						{@const runA = runs.find(r => r.run_id === runAId)}
						<div class="flex justify-between text-xs">
							<span class="text-base-content/70">{metric.replace('_', ' ')}</span>
							<span class="{delta > 0.01 ? 'text-success font-bold' : delta < -0.01 ? 'text-error' : ''}">
								{runA ? formatPercent(runA.metric_averages[metric]) : '-'}
							</span>
						</div>
					{/each}
					{#if comparison.latency_delta_ms != null}
						{@const latencyDelta = comparison.latency_delta_ms}
						<div class="divider my-1"></div>
						<div class="flex justify-between text-xs">
							<span class="text-base-content/70">Latency</span>
							<span class="{latencyDelta > 0 ? 'text-success' : latencyDelta < 0 ? 'text-error' : ''}">
								{latencyDelta > 0 ? 'Faster' : latencyDelta < 0 ? 'Slower' : 'Same'}
							</span>
						</div>
					{/if}
				</div>

				<!-- Run B -->
				<div class="bg-base-100 rounded p-2">
					<div class="text-xs font-semibold mb-1">
						{comparison.run_b_config?.llm_model || 'Run B'}
					</div>
					{#each Object.entries(comparison.metric_deltas) as [metric, delta]}
						{@const runB = runs.find(r => r.run_id === runBId)}
						<div class="flex justify-between text-xs">
							<span class="text-base-content/70">{metric.replace('_', ' ')}</span>
							<span class="{delta < -0.01 ? 'text-success font-bold' : delta > 0.01 ? 'text-error' : ''}">
								{runB ? formatPercent(runB.metric_averages[metric]) : '-'}
							</span>
						</div>
					{/each}
					{#if comparison.latency_delta_ms != null}
						{@const latencyDelta = comparison.latency_delta_ms}
						<div class="divider my-1"></div>
						<div class="flex justify-between text-xs">
							<span class="text-base-content/70">Latency</span>
							<span class="{latencyDelta < 0 ? 'text-success' : latencyDelta > 0 ? 'text-error' : ''}">
								{latencyDelta < 0 ? 'Faster' : latencyDelta > 0 ? 'Slower' : 'Same'}
							</span>
						</div>
					{/if}
				</div>
			</div>

			<!-- Winner -->
			<div class="flex items-center justify-center gap-2 mt-3">
				{#if comparison.winner === 'run_a'}
					<span class="badge badge-success badge-sm">
						Winner: {comparison.run_a_config?.llm_model || 'Run A'}
					</span>
				{:else if comparison.winner === 'run_b'}
					<span class="badge badge-success badge-sm">
						Winner: {comparison.run_b_config?.llm_model || 'Run B'}
					</span>
				{:else}
					<span class="badge badge-warning badge-sm">Tie</span>
				{/if}
				<span class="text-xs text-base-content/60">{comparison.winner_reason}</span>
			</div>
		{/if}
	{/if}
</div>
