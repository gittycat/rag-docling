<script lang="ts">
	import type { EvaluationRun, GoldenBaseline } from '$lib/api';
	import { setGoldenBaseline, clearGoldenBaseline } from '$lib/api';

	interface Props {
		currentRun: EvaluationRun | null;
		baseline: GoldenBaseline | null;
		onBaselineChange?: () => void;
	}

	let { currentRun, baseline, onBaselineChange }: Props = $props();

	let isSettingBaseline = $state(false);
	let error = $state<string | null>(null);

	// Calculate pass/fail status for each metric
	let passStatus = $derived.by(() => {
		if (!currentRun || !baseline) return null;

		const results: Record<string, { passed: boolean; delta: number }> = {};

		for (const [metric, threshold] of Object.entries(baseline.target_metrics)) {
			const actual = currentRun.metric_averages[metric];
			if (actual === undefined) continue;

			// For hallucination, lower is better
			if (metric === 'hallucination') {
				const passed = actual <= threshold;
				results[metric] = { passed, delta: threshold - actual };
			} else {
				const passed = actual >= threshold;
				results[metric] = { passed, delta: actual - threshold };
			}
		}

		return results;
	});

	let overallPass = $derived.by(() => {
		if (!passStatus) return null;
		return Object.values(passStatus).every((r) => r.passed);
	});

	async function handleSetBaseline() {
		if (!currentRun) return;
		isSettingBaseline = true;
		error = null;
		try {
			await setGoldenBaseline(currentRun.run_id);
			onBaselineChange?.();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to set baseline';
		} finally {
			isSettingBaseline = false;
		}
	}

	async function handleClearBaseline() {
		isSettingBaseline = true;
		error = null;
		try {
			await clearGoldenBaseline();
			onBaselineChange?.();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to clear baseline';
		} finally {
			isSettingBaseline = false;
		}
	}

	function timeAgo(timestamp: string): string {
		const diff = Date.now() - new Date(timestamp).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	function formatPercent(value: number): string {
		return `${(value * 100).toFixed(1)}%`;
	}
</script>

<div class="baseline-indicator">
	{#if baseline}
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-2">
				<span class="badge badge-outline badge-sm">Golden Baseline</span>
				<span class="text-xs font-mono">{baseline.config_snapshot.llm_model}</span>
				<span class="text-xs text-base-content/60">Set {timeAgo(baseline.set_at)}</span>
			</div>
			<button
				class="btn btn-ghost btn-xs text-error"
				onclick={handleClearBaseline}
				disabled={isSettingBaseline}
			>
				Clear
			</button>
		</div>

		{#if passStatus && currentRun}
			<div class="flex flex-wrap gap-1 mt-2">
				{#each Object.entries(passStatus) as [metric, result]}
					<div
						class="tooltip"
						data-tip="{metric}: {formatPercent(currentRun.metric_averages[metric])} (delta: {result.delta > 0 ? '+' : ''}{(result.delta * 100).toFixed(1)}%)"
					>
						<span class="badge badge-xs {result.passed ? 'badge-success' : 'badge-error'}">
							{metric.replace('_', ' ')}
						</span>
					</div>
				{/each}
			</div>

			<div class="flex items-center gap-2 mt-2">
				{#if overallPass}
					<span class="badge badge-success badge-sm">BASELINE PASSED</span>
				{:else}
					<span class="badge badge-error badge-sm">BASELINE FAILED</span>
				{/if}
			</div>
		{/if}
	{:else if currentRun}
		<div class="flex items-center justify-between">
			<span class="text-xs text-base-content/60">No baseline set</span>
			<button
				class="btn btn-ghost btn-xs"
				onclick={handleSetBaseline}
				disabled={isSettingBaseline}
			>
				{isSettingBaseline ? 'Setting...' : 'Set Current as Baseline'}
			</button>
		</div>
	{:else}
		<span class="text-xs text-base-content/60">Run an evaluation to set a baseline</span>
	{/if}

	{#if error}
		<div class="text-xs text-error mt-1">{error}</div>
	{/if}
</div>
