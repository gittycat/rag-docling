<script lang="ts">
	import { onMount } from 'svelte';
	import type { EvaluationRun } from '$lib/api';
	import { fetchEvaluationHistory } from '$lib/api';
	import Sparkline from '$lib/components/Sparkline.svelte';

	interface Props {
		onSelectRun?: (runId: string) => void;
	}

	let { onSelectRun }: Props = $props();

	let runs = $state<EvaluationRun[]>([]);
	let isLoading = $state(true);
	let error = $state<string | null>(null);
	let sortField = $state<'timestamp' | 'pass_rate' | 'model'>('timestamp');
	let sortOrder = $state<'asc' | 'desc'>('desc');

	let sortedRuns = $derived.by(() => {
		const sorted = [...runs];
		sorted.sort((a, b) => {
			let aVal: string | number;
			let bVal: string | number;

			switch (sortField) {
				case 'timestamp':
					aVal = new Date(a.timestamp).getTime();
					bVal = new Date(b.timestamp).getTime();
					break;
				case 'pass_rate':
					aVal = a.pass_rate;
					bVal = b.pass_rate;
					break;
				case 'model':
					aVal = a.config_snapshot?.llm_model || '';
					bVal = b.config_snapshot?.llm_model || '';
					break;
				default:
					return 0;
			}

			if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
			if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
			return 0;
		});
		return sorted;
	});

	onMount(() => {
		loadData();
	});

	async function loadData() {
		isLoading = true;
		error = null;

		try {
			runs = await fetchEvaluationHistory(50);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load history';
		} finally {
			isLoading = false;
		}
	}

	function toggleSort(field: typeof sortField) {
		if (sortField === field) {
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			sortField = field;
			sortOrder = 'desc';
		}
	}

	function formatDateTime(timestamp: string): string {
		const date = new Date(timestamp);
		return date.toLocaleString('en-US', {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
			hour12: false
		});
	}

	function getPassRateBadge(rate: number): string {
		if (rate >= 0.8) return 'badge-success';
		if (rate >= 0.6) return 'badge-warning';
		return 'badge-error';
	}

	function getSortIcon(field: typeof sortField): string {
		if (sortField !== field) return '↕';
		return sortOrder === 'asc' ? '↑' : '↓';
	}

	// Get metric values for sparkline (last N runs, reversed for chronological order)
	function getMetricTrend(metricName: string): number[] {
		return runs
			.slice(0, 10)
			.map((r) => (r.metric_averages[metricName] ?? 0) * 100)
			.reverse();
	}

	// Get unique metrics from all runs
	let allMetrics = $derived.by(() => {
		const metrics = new Set<string>();
		for (const run of runs) {
			for (const m of Object.keys(run.metric_averages)) {
				metrics.add(m);
			}
		}
		return Array.from(metrics).sort();
	});
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
			No evaluation runs found. Run an evaluation to see results here.
		</div>
	{:else}
		<!-- Metric Trends Summary -->
		{#if allMetrics.length > 0}
			<div class="bg-base-200 rounded p-2">
				<div class="text-xs font-semibold mb-2 text-base-content/70">
					Metric Trends (Last 10 Runs)
				</div>
				<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
					{#each allMetrics as metric}
						<div class="bg-base-100 rounded p-2 text-center">
							<div class="text-xs text-base-content/70 truncate" title={metric}>
								{metric.replace(/_/g, ' ')}
							</div>
							<div class="mt-1">
								<Sparkline values={getMetricTrend(metric)} strokeColor="oklch(var(--p))" />
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- History Table -->
		<div class="overflow-x-auto">
			<table class="table table-xs table-pin-rows">
				<thead class="bg-base-200">
					<tr>
						<th class="cursor-pointer" onclick={() => toggleSort('timestamp')}>
							Timestamp {getSortIcon('timestamp')}
						</th>
						<th class="cursor-pointer" onclick={() => toggleSort('model')}>
							Model {getSortIcon('model')}
						</th>
						<th>Search Type</th>
						<th class="cursor-pointer text-right" onclick={() => toggleSort('pass_rate')}>
							Pass Rate {getSortIcon('pass_rate')}
						</th>
						<th class="text-right">Tests</th>
						<th class="text-right">Latency</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{#each sortedRuns as run}
						<tr class="hover">
							<td class="text-xs">
								{formatDateTime(run.timestamp)}
								{#if run.is_golden_baseline}
									<span class="badge badge-xs badge-warning ml-1">baseline</span>
								{/if}
							</td>
							<td class="font-mono text-xs truncate max-w-32" title={run.config_snapshot?.llm_model}>
								{run.config_snapshot?.llm_model || '-'}
							</td>
							<td class="text-xs">
								{#if run.config_snapshot?.hybrid_search_enabled}
									<span class="badge badge-xs badge-info">Hybrid</span>
								{:else}
									<span class="badge badge-xs badge-ghost">Vector</span>
								{/if}
							</td>
							<td class="text-right">
								<span class="badge badge-xs {getPassRateBadge(run.pass_rate)}">
									{(run.pass_rate * 100).toFixed(0)}%
								</span>
							</td>
							<td class="text-right text-xs text-base-content/70">
								{run.passed_tests}/{run.total_tests}
							</td>
							<td class="text-right text-xs text-base-content/70">
								{#if run.latency?.avg_query_time_ms}
									{run.latency.avg_query_time_ms.toFixed(0)}ms
								{:else}
									-
								{/if}
							</td>
							<td class="text-right">
								{#if onSelectRun}
									<button
										class="btn btn-xs btn-ghost"
										onclick={() => onSelectRun?.(run.run_id)}
										title="Add to comparison"
									>
										+
									</button>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<div class="text-xs text-base-content/50 text-center">
			Showing {runs.length} evaluation runs
		</div>
	{/if}
</div>
