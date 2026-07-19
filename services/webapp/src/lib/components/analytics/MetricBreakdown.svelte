<script lang="ts">
	import type { EvalRunDetail, ScorecardMetric } from '$lib/api/evals';
	import type { Bracket, BracketHealth } from '$lib/utils/stageHealth';
	import { bracketForGroup } from '$lib/utils/stageHealth';
	import { thresholdColorClass } from '$lib/utils/thresholds';
	import { metricDescription, metricLabel, STAGE_INFO } from '$lib/utils/metricInfo';
	import InfoTip from './InfoTip.svelte';
	import HealthBadge from './HealthBadge.svelte';

	interface Props {
		detail: EvalRunDetail | null;
		bracketHealth: Record<Bracket, BracketHealth>;
	}

	let { detail, bracketHealth }: Props = $props();

	const GROUP_ORDER = ['retrieval', 'generation', 'citation', 'abstention'];
	const GROUP_LABELS: Record<string, string> = {
		retrieval: 'Retrieval',
		generation: 'Generation',
		citation: 'Citation',
		abstention: 'Abstention'
	};

	// One representative "if weak, try" tip per group, reused from STAGE_INFO.
	const GROUP_TIP: Record<string, string> = {
		retrieval: STAGE_INFO.hybrid_search.ifWeak,
		generation: STAGE_INFO.llm.ifWeak,
		citation: STAGE_INFO.llm.ifWeak,
		abstention: STAGE_INFO.llm.ifWeak
	};

	function metricsByGroup(group: string): ScorecardMetric[] {
		return detail?.scorecard?.metrics.filter((m) => m.group === group) ?? [];
	}

	// Pill background tint derived from the metric's threshold band.
	function pillClass(name: string, value: number): string {
		const c = thresholdColorClass(name, value);
		if (c === 'text-success') return 'bg-success/15 text-success';
		if (c === 'text-warning') return 'bg-warning/15 text-warning';
		if (c === 'text-error') return 'bg-error/15 text-error';
		return 'bg-base-300/50 text-base-content/70';
	}
</script>

<div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
	{#each GROUP_ORDER as group}
		{@const groupMetrics = metricsByGroup(group)}
		{@const bracket = bracketForGroup(group)}
		{@const health = bracket ? bracketHealth[bracket].health : 'unknown'}
		{@const weak = health === 'warn' || health === 'bad'}
		<div class="term-panel flex flex-col gap-2">
			<div class="flex items-center justify-between">
				<span class="term-label">{GROUP_LABELS[group]}</span>
				{#if bracket}<HealthBadge {health} />{/if}
			</div>

			{#if group === 'retrieval' && detail?.tier === 'generation'}
				<div class="text-center py-3 text-base-content/40 text-xs font-mono">n/a (generation tier)</div>
			{:else if groupMetrics.length === 0}
				<div class="text-center py-3 text-base-content/40 text-xs">{detail ? 'no data' : 'awaiting first run'}</div>
			{:else}
				<div class="flex flex-col divide-y divide-base-content/5">
					{#each groupMetrics as m}
						{@const desc = metricDescription(m.name)}
						<div class="flex items-center justify-between gap-2 py-1">
							<span class="capitalize text-xs inline-flex items-center gap-1">
								{metricLabel(m.name)}
								{#if desc}<InfoTip text={desc} />{/if}
								{#if group === 'generation' && typeof m.details?.std_dev === 'number'}
									<span class="text-base-content/40 text-[10px]">±{((m.details.std_dev as number) * 100).toFixed(1)}%</span>
								{/if}
							</span>
							<span class="px-1.5 py-0.5 rounded-sm font-mono tabular-nums text-xs {pillClass(m.name, m.value)}">
								{(m.value * 100).toFixed(1)}%
							</span>
						</div>
					{/each}
				</div>

				{#if GROUP_TIP[group]}
					<details class="text-xs" open={weak}>
						<summary class="cursor-pointer text-base-content/60 font-semibold select-none">
							If this is weak, try…
						</summary>
						<p class="mt-1 text-base-content/60 bg-base-100 border border-base-content/10 rounded-sm p-2">
							{GROUP_TIP[group]}
						</p>
					</details>
				{/if}
			{/if}
		</div>
	{/each}
</div>
