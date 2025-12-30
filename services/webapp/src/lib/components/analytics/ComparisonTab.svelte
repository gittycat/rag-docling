<script lang="ts">
	import { onMount } from 'svelte';
	import type { EvaluationRun, GoldenBaseline, EvaluationSummary } from '$lib/api';
	import { fetchEvaluationHistory, fetchGoldenBaseline, setGoldenBaseline, clearGoldenBaseline } from '$lib/api';
	import MetricsBarChart from '$lib/components/charts/MetricsBarChart.svelte';
	import RunSelector from '$lib/components/RunSelector.svelte';
	import ExportButton from '$lib/components/ExportButton.svelte';
	import BaselineIndicator from '$lib/components/BaselineIndicator.svelte';

	interface Props {
		evalSummary: EvaluationSummary | null;
		onRefresh?: () => void;
	}

	let { evalSummary, onRefresh }: Props = $props();

	let runs = $state<EvaluationRun[]>([]);
	let baseline = $state<GoldenBaseline | null>(null);
	let selectedRunIds = $state<string[]>([]);
	let isLoading = $state(true);
	let error = $state<string | null>(null);
	let previousRunIds = $state<Set<string>>(new Set());
	let autoAppend = $state(true);

	// Selected runs for chart
	let selectedRuns = $derived(
		runs.filter((r) => selectedRunIds.includes(r.run_id))
	);

	// Latest run for baseline indicator
	let latestRun = $derived(runs.length > 0 ? runs[0] : null);

	onMount(() => {
		loadData();
	});

	async function loadData() {
		isLoading = true;
		error = null;

		try {
			const [runsData, baselineData] = await Promise.all([
				fetchEvaluationHistory(20),
				fetchGoldenBaseline().catch(() => null)
			]);

			// Detect new runs for auto-append
			const currentIds = new Set(runsData.map((r) => r.run_id));
			if (autoAppend && previousRunIds.size > 0) {
				const newRuns = runsData.filter((r) => !previousRunIds.has(r.run_id));
				if (newRuns.length > 0) {
					// Add new runs to selection (respecting max limit of 8)
					const newIds = newRuns.map((r) => r.run_id);
					selectedRunIds = [...newIds, ...selectedRunIds].slice(0, 8);
				}
			}
			previousRunIds = currentIds;

			runs = runsData;
			baseline = baselineData;

			// Auto-select first 2 runs if nothing selected
			if (selectedRunIds.length === 0 && runs.length >= 2) {
				selectedRunIds = runs.slice(0, 2).map((r) => r.run_id);
			} else if (selectedRunIds.length === 0 && runs.length === 1) {
				selectedRunIds = [runs[0].run_id];
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load data';
		} finally {
			isLoading = false;
		}
	}

	async function handleBaselineChange() {
		// Reload baseline after change
		try {
			baseline = await fetchGoldenBaseline().catch(() => null);
			if (onRefresh) onRefresh();
		} catch {
			// Ignore errors
		}
	}

	function handleSelectionChange(ids: string[]) {
		selectedRunIds = ids;
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
	{:else}
		<!-- Controls Row -->
		<div class="flex items-center gap-3 flex-wrap">
			<div class="flex-1 min-w-0">
				<label class="flex items-center gap-2 text-xs text-base-content/70">
					<input
						type="checkbox"
						class="checkbox checkbox-xs"
						bind:checked={autoAppend}
					/>
					Auto-append new runs
				</label>
			</div>
			<ExportButton {runs} {baseline} disabled={selectedRuns.length === 0} />
			<button class="btn btn-sm btn-ghost" onclick={loadData}>
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
				</svg>
				Refresh
			</button>
		</div>

		<!-- Main Content Grid -->
		<div class="grid grid-cols-1 lg:grid-cols-4 gap-3">
			<!-- Run Selector (Left Column) -->
			<div class="lg:col-span-1">
				<RunSelector
					{runs}
					selected={selectedRunIds}
					onSelectionChange={handleSelectionChange}
					maxSelection={8}
				/>
			</div>

			<!-- Chart (Right Column) -->
			<div class="lg:col-span-3">
				<div class="bg-base-200 rounded p-3">
					<div class="text-xs font-semibold mb-2 text-base-content/70">
						Metrics Comparison
						{#if baseline}
							<span class="badge badge-xs badge-warning ml-2">Baseline shown</span>
						{/if}
					</div>
					<MetricsBarChart runs={selectedRuns} {baseline} height={320} />
				</div>
			</div>
		</div>

		<!-- Baseline Indicator -->
		{#if latestRun}
			<BaselineIndicator
				currentRun={latestRun}
				{baseline}
				onBaselineChange={handleBaselineChange}
			/>
		{/if}
	{/if}
</div>
