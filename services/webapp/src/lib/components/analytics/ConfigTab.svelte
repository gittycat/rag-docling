<script lang="ts">
	import { onMount } from 'svelte';
	import type { EvaluationRun } from '$lib/api';
	import { fetchEvaluationHistory } from '$lib/api';
	import ConfigDiff from '$lib/components/ConfigDiff.svelte';

	let runs = $state<EvaluationRun[]>([]);
	let isLoading = $state(true);
	let error = $state<string | null>(null);
	let runAId = $state<string>('');
	let runBId = $state<string>('');
	let showUnchanged = $state(false);

	let runA = $derived(runs.find((r) => r.run_id === runAId));
	let runB = $derived(runs.find((r) => r.run_id === runBId));

	onMount(() => {
		loadData();
	});

	async function loadData() {
		isLoading = true;
		error = null;

		try {
			runs = await fetchEvaluationHistory(20);

			// Auto-select first two runs
			if (runs.length >= 2) {
				runAId = runs[1].run_id; // Older run as "before"
				runBId = runs[0].run_id; // Newer run as "after"
			} else if (runs.length === 1) {
				runBId = runs[0].run_id;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load runs';
		} finally {
			isLoading = false;
		}
	}

	function getRunLabel(run: EvaluationRun): string {
		const model = run.config_snapshot?.llm_model || 'Unknown';
		const time = new Date(run.timestamp).toLocaleString('en-US', {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
			hour12: false
		});
		return `${model} (${time})`;
	}

	function swapRuns() {
		const temp = runAId;
		runAId = runBId;
		runBId = temp;
	}
</script>

<div class="flex flex-col gap-3">
	{#if isLoading}
		<div class="flex items-center justify-center h-64">
			<span class="loading loading-spinner loading-lg"></span>
		</div>
	{:else if error}
		<div class="alert alert-error">
			<span>{error}</span>
			<button class="btn btn-sm" onclick={loadData}>Retry</button>
		</div>
	{:else if runs.length === 0}
		<div class="text-center py-8 text-base-content/50">
			No evaluation runs found. Run an evaluation to compare configurations.
		</div>
	{:else}
		<!-- Run Selectors -->
		<div class="bg-base-200 rounded p-3">
			<div class="text-xs font-semibold mb-3 text-base-content/70">
				Compare Configurations
			</div>

			<div class="flex flex-wrap items-center gap-3">
				<div class="flex-1 min-w-48">
					<label class="text-xs text-base-content/50 block mb-1" for="run-a-select">Before (Run A)</label>
					<select
						id="run-a-select"
						class="select select-sm select-bordered w-full font-mono text-xs"
						bind:value={runAId}
					>
						<option value="">Select a run...</option>
						{#each runs as run}
							<option value={run.run_id}>{getRunLabel(run)}</option>
						{/each}
					</select>
				</div>

				<button
					class="btn btn-sm btn-square btn-ghost mt-5"
					onclick={swapRuns}
					title="Swap runs"
					disabled={!runAId || !runBId}
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
					</svg>
				</button>

				<div class="flex-1 min-w-48">
					<label class="text-xs text-base-content/50 block mb-1" for="run-b-select">After (Run B)</label>
					<select
						id="run-b-select"
						class="select select-sm select-bordered w-full font-mono text-xs"
						bind:value={runBId}
					>
						<option value="">Select a run...</option>
						{#each runs as run}
							<option value={run.run_id}>{getRunLabel(run)}</option>
						{/each}
					</select>
				</div>
			</div>

			<div class="mt-3">
				<label class="flex items-center gap-2 text-xs text-base-content/70">
					<input
						type="checkbox"
						class="checkbox checkbox-xs"
						bind:checked={showUnchanged}
					/>
					Show unchanged fields
				</label>
			</div>
		</div>

		<!-- Config Diff -->
		<ConfigDiff
			configA={runA?.config_snapshot}
			configB={runB?.config_snapshot}
			labelA={runA ? getRunLabel(runA) : 'Run A'}
			labelB={runB ? getRunLabel(runB) : 'Run B'}
			{showUnchanged}
		/>

		<!-- Performance Comparison -->
		{#if runA && runB}
			<div class="bg-base-200 rounded p-3">
				<div class="text-xs font-semibold mb-2 text-base-content/70">
					Performance Comparison
				</div>
				<div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-center">
					<div class="bg-base-100 rounded p-2">
						<div class="text-xs text-base-content/50">Pass Rate</div>
						<div class="flex items-center justify-center gap-2 mt-1">
							<span class="text-sm">{(runA.pass_rate * 100).toFixed(0)}%</span>
							<span class="text-base-content/30">→</span>
							<span class="text-sm font-semibold {runB.pass_rate > runA.pass_rate ? 'text-success' : runB.pass_rate < runA.pass_rate ? 'text-error' : ''}">
								{(runB.pass_rate * 100).toFixed(0)}%
							</span>
						</div>
					</div>
					<div class="bg-base-100 rounded p-2">
						<div class="text-xs text-base-content/50">Avg Latency</div>
						<div class="flex items-center justify-center gap-2 mt-1">
							<span class="text-sm">{runA.latency?.avg_query_time_ms?.toFixed(0) || '-'}ms</span>
							<span class="text-base-content/30">→</span>
							<span class="text-sm font-semibold {(runB.latency?.avg_query_time_ms || 0) < (runA.latency?.avg_query_time_ms || 0) ? 'text-success' : (runB.latency?.avg_query_time_ms || 0) > (runA.latency?.avg_query_time_ms || 0) ? 'text-error' : ''}">
								{runB.latency?.avg_query_time_ms?.toFixed(0) || '-'}ms
							</span>
						</div>
					</div>
					<div class="bg-base-100 rounded p-2">
						<div class="text-xs text-base-content/50">Tests Passed</div>
						<div class="flex items-center justify-center gap-2 mt-1">
							<span class="text-sm">{runA.passed_tests}/{runA.total_tests}</span>
							<span class="text-base-content/30">→</span>
							<span class="text-sm font-semibold {runB.passed_tests > runA.passed_tests ? 'text-success' : runB.passed_tests < runA.passed_tests ? 'text-error' : ''}">
								{runB.passed_tests}/{runB.total_tests}
							</span>
						</div>
					</div>
					<div class="bg-base-100 rounded p-2">
						<div class="text-xs text-base-content/50">Cost/Query</div>
						<div class="flex items-center justify-center gap-2 mt-1">
							<span class="text-sm">${runA.cost?.cost_per_query_usd?.toFixed(4) || '-'}</span>
							<span class="text-base-content/30">→</span>
							<span class="text-sm font-semibold {(runB.cost?.cost_per_query_usd || 0) < (runA.cost?.cost_per_query_usd || 0) ? 'text-success' : (runB.cost?.cost_per_query_usd || 0) > (runA.cost?.cost_per_query_usd || 0) ? 'text-error' : ''}">
								${runB.cost?.cost_per_query_usd?.toFixed(4) || '-'}
							</span>
						</div>
					</div>
				</div>
			</div>
		{/if}
	{/if}
</div>
