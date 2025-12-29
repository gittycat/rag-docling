<script lang="ts">
	import { fetchRecommendation, type Recommendation } from '$lib/api';

	let accuracyWeight = $state(0.5);
	let speedWeight = $state(0.3);
	let costWeight = $state(0.2);

	let recommendation = $state<Recommendation | null>(null);
	let isLoading = $state(false);
	let error = $state<string | null>(null);

	async function loadRecommendation() {
		isLoading = true;
		error = null;
		try {
			recommendation = await fetchRecommendation(accuracyWeight, speedWeight, costWeight);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to get recommendation';
			recommendation = null;
		} finally {
			isLoading = false;
		}
	}

	function handleWeightChange() {
		// Debounce the API call
		clearTimeout(debounceTimer);
		debounceTimer = window.setTimeout(() => {
			loadRecommendation();
		}, 500);
	}

	let debounceTimer: number;

	function formatPercent(value: number): string {
		return `${(value * 100).toFixed(0)}%`;
	}

	function getScoreColor(score: number): string {
		if (score >= 0.7) return 'text-success';
		if (score >= 0.5) return 'text-warning';
		return 'text-error';
	}

	// Load on mount
	$effect(() => {
		loadRecommendation();
	});
</script>

<div class="recommendation-panel bg-base-200 rounded p-3">
	<div class="text-xs font-semibold mb-2 text-base-content/70">Configuration Recommendation</div>

	<!-- Weight Sliders -->
	<div class="grid grid-cols-3 gap-3 mb-3">
		<label class="flex flex-col">
			<span class="text-xs text-base-content/60 mb-1">Accuracy: {formatPercent(accuracyWeight)}</span>
			<input
				type="range"
				min="0"
				max="1"
				step="0.1"
				bind:value={accuracyWeight}
				oninput={handleWeightChange}
				class="range range-xs range-primary"
			/>
		</label>
		<label class="flex flex-col">
			<span class="text-xs text-base-content/60 mb-1">Speed: {formatPercent(speedWeight)}</span>
			<input
				type="range"
				min="0"
				max="1"
				step="0.1"
				bind:value={speedWeight}
				oninput={handleWeightChange}
				class="range range-xs range-secondary"
			/>
		</label>
		<label class="flex flex-col">
			<span class="text-xs text-base-content/60 mb-1">Cost: {formatPercent(costWeight)}</span>
			<input
				type="range"
				min="0"
				max="1"
				step="0.1"
				bind:value={costWeight}
				oninput={handleWeightChange}
				class="range range-xs range-accent"
			/>
		</label>
	</div>

	{#if isLoading}
		<div class="flex items-center justify-center py-4">
			<span class="loading loading-spinner loading-sm"></span>
		</div>
	{:else if error}
		<div class="text-xs text-base-content/60 py-2">{error}</div>
	{:else if recommendation}
		<!-- Recommended Config -->
		<div class="bg-base-100 rounded p-2 mb-2">
			<div class="flex items-center gap-2">
				<span class="badge badge-primary badge-sm">Recommended</span>
				<span class="font-mono text-sm">{recommendation.recommended_config.llm_model}</span>
			</div>
			<p class="text-xs text-base-content/70 mt-1">{recommendation.reasoning}</p>
		</div>

		<!-- Score Breakdown -->
		<div class="grid grid-cols-3 gap-2 text-center text-xs">
			<div>
				<div class="text-base-content/60">Accuracy</div>
				<div class="font-bold {getScoreColor(recommendation.accuracy_score)}">
					{formatPercent(recommendation.accuracy_score)}
				</div>
			</div>
			<div>
				<div class="text-base-content/60">Speed</div>
				<div class="font-bold {getScoreColor(recommendation.speed_score)}">
					{formatPercent(recommendation.speed_score)}
				</div>
			</div>
			<div>
				<div class="text-base-content/60">Cost</div>
				<div class="font-bold {getScoreColor(recommendation.cost_score)}">
					{formatPercent(recommendation.cost_score)}
				</div>
			</div>
		</div>

		<!-- Alternatives -->
		{#if recommendation.alternatives.length > 0}
			<details class="mt-2">
				<summary class="text-xs cursor-pointer text-base-content/70">
					Alternatives ({recommendation.alternatives.length})
				</summary>
				<ul class="text-xs mt-1 space-y-1">
					{#each recommendation.alternatives as alt}
						<li class="flex justify-between bg-base-100 rounded px-2 py-1">
							<span class="font-mono">{alt.model}</span>
							<span class="text-base-content/60">{alt.reason}</span>
						</li>
					{/each}
				</ul>
			</details>
		{/if}
	{:else}
		<div class="text-xs text-base-content/60 py-2">
			Run at least 2 evaluations to get recommendations
		</div>
	{/if}
</div>
