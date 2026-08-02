<script lang="ts">
	import type { WeightedScoreDetail } from '$lib/api/evals';
	import InfoTip from './InfoTip.svelte';

	interface Props {
		weighted: WeightedScoreDetail | null | undefined;
	}

	let { weighted }: Props = $props();

	interface Row {
		objective: string;
		weight: number;
		/** Weight as a share of the weights that actually had data. */
		share: number;
		score: number | null;
		contribution: number;
		/** Contribution as a share of the final weighted score. */
		scoreShare: number;
	}

	// Objectives with no data are excluded by the runner and their weight is
	// redistributed, so the effective share is weight / sum(weights with data).
	let rows = $derived.by((): Row[] => {
		if (!weighted) return [];
		const objectives = weighted.objectives ?? {};
		const weights = weighted.weights ?? {};
		const contributions = weighted.contributions ?? {};

		const active = Object.keys(objectives);
		const totalWeight = active.reduce((sum, o) => sum + (weights[o] ?? 0), 0);
		const totalContribution = active.reduce((sum, o) => sum + (contributions[o] ?? 0), 0);

		return active
			.map((objective): Row => {
				const weight = weights[objective] ?? 0;
				const contribution = contributions[objective] ?? 0;
				return {
					objective,
					weight,
					share: totalWeight > 0 ? weight / totalWeight : 0,
					score: objectives[objective] ?? null,
					contribution,
					scoreShare: totalContribution > 0 ? contribution / totalContribution : 0
				};
			})
			.sort((a, b) => b.scoreShare - a.scoreShare);
	});

	// Weights configured for objectives the run produced no data for.
	let inactive = $derived.by(() => {
		if (!weighted) return [] as string[];
		const objectives = weighted.objectives ?? {};
		return Object.keys(weighted.weights ?? {}).filter((o) => !(o in objectives));
	});

	function pct(v: number | null): string {
		return v != null ? `${(v * 100).toFixed(1)}%` : '—';
	}
</script>

<div class="term-panel flex flex-col gap-2">
	<div class="flex items-center justify-between gap-2">
		<span class="term-label inline-flex items-center gap-1">
			Weighted score breakdown
			<InfoTip
				text="The headline score is an opinionated aggregate: each objective's score times its weight, divided by the total weight of objectives that had data. Objectives with no data are excluded and their weight is redistributed."
			/>
		</span>
		{#if weighted}
			<span class="font-mono tabular-nums text-sm">{pct(weighted.score)}</span>
		{/if}
	</div>

	{#if !weighted || rows.length === 0}
		<div class="text-center py-3 text-base-content/40 text-xs">
			{weighted ? 'no objectives scored' : 'awaiting first run'}
		</div>
	{:else}
		<div class="overflow-x-auto">
			<table class="table table-xs term-table">
				<thead>
					<tr>
						<th>Objective</th>
						<th class="text-right">Weight</th>
						<th class="text-right">Effective</th>
						<th class="text-right">Score</th>
						<th class="text-right">Contribution</th>
						<th class="w-32">Share of total</th>
					</tr>
				</thead>
				<tbody>
					{#each rows as row}
						<tr class="hover">
							<td class="capitalize">{row.objective.replace(/_/g, ' ')}</td>
							<td class="text-right term-num">{row.weight.toFixed(2)}</td>
							<td class="text-right term-num text-base-content/60">{(row.share * 100).toFixed(0)}%</td>
							<td class="text-right term-num">{pct(row.score)}</td>
							<td class="text-right term-num">{row.contribution.toFixed(3)}</td>
							<td>
								<div class="flex items-center gap-1.5">
									<div class="flex-1 h-1.5 bg-base-300/60 rounded-sm overflow-hidden">
										<div class="h-full bg-primary" style="width: {(row.scoreShare * 100).toFixed(1)}%"></div>
									</div>
									<span class="font-mono tabular-nums text-[10px] text-base-content/60 w-8 text-right">
										{(row.scoreShare * 100).toFixed(0)}%
									</span>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		{#if inactive.length > 0}
			<div class="text-[10px] text-base-content/50 font-mono">
				No data (weight redistributed): {inactive.join(', ')}
			</div>
		{/if}
	{/if}
</div>
