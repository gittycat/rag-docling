<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchEvalRuns,
		compareEvalRuns,
		type EvalRunSummary,
		type EvalRunDetail,
		type EvalCompareResponse
	} from '$lib/api/evals';
	import RunSelector from '$lib/components/RunSelector.svelte';
	import ExportButton from '$lib/components/ExportButton.svelte';
	import ConfigDiff from '$lib/components/ConfigDiff.svelte';
	import InfoTip from './InfoTip.svelte';
	import MetricSparkline from './MetricSparkline.svelte';
	import { getMetricThreshold, deltaColorClass } from '$lib/utils/thresholds';
	import { metricDescription, metricLabel, formatDelta, panelDescription, type DeltaFormat } from '$lib/utils/metricInfo';

	interface Props {
		onRefresh?: () => void;
	}
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	let { onRefresh }: Props = $props();

	let runs = $state<EvalRunSummary[]>([]);
	let selectedRunIds = $state<string[]>([]);
	let compareResult = $state<EvalCompareResponse | null>(null);
	let isLoading = $state(true);
	let isComparing = $state(false);
	let error = $state<string | null>(null);
	let hideUnchanged = $state(false);

	const RUN_LETTERS = ['A', 'B', 'C', 'D'];
	const GROUP_LABELS: Record<string, string> = {
		headline: 'Headline',
		retrieval: 'Retrieval',
		generation: 'Generation',
		citation: 'Citation',
		abstention: 'Abstention',
		cost_speed: 'Cost & speed'
	};
	const GROUP_ORDER = ['headline', 'retrieval', 'generation', 'citation', 'abstention', 'cost_speed'];

	// Row descriptor: how to pull + format a value across runs.
	interface Row {
		name: string;
		group: string;
		format: DeltaFormat;
		colorDelta: boolean;
	}

	const EPS: Record<DeltaFormat, number> = { pts: 0.005, usd: 0.0001, seconds: 0.05, int: 0.5 };

	let selectedSummaries = $derived(runs.filter((r) => selectedRunIds.includes(r.id)));

	let orderedSelectedIds = $derived.by(() => {
		const createdAt = new Map(runs.map((r) => [r.id, new Date(r.created_at).getTime()]));
		return [...selectedRunIds].sort((a, b) => (createdAt.get(a) ?? 0) - (createdAt.get(b) ?? 0));
	});

	// Build the ordered row list: headline score, per-group scorecard metrics, then cost/speed.
	let rows = $derived.by((): Row[] => {
		if (!compareResult) return [];
		const out: Row[] = [{ name: 'weighted_score', group: 'headline', format: 'pts', colorDelta: true }];

		const names = new Set<string>();
		const groupOf: Record<string, string> = {};
		for (const run of compareResult.runs) {
			for (const [group, metricNames] of Object.entries(run.scorecard?.by_group ?? {})) {
				if (group === 'performance') continue;
				for (const n of metricNames) {
					names.add(n);
					groupOf[n] = group;
				}
			}
		}
		const groupRank = (g: string) => {
			const i = GROUP_ORDER.indexOf(g);
			return i === -1 ? GROUP_ORDER.length : i;
		};
		const metricRows = Array.from(names)
			.sort((a, b) => groupRank(groupOf[a]) - groupRank(groupOf[b]) || a.localeCompare(b))
			.map((name): Row => ({ name, group: groupOf[name], format: 'pts', colorDelta: true }));
		out.push(...metricRows);

		out.push(
			{ name: 'avg_cost_usd', group: 'cost_speed', format: 'usd', colorDelta: true },
			{ name: 'latency_p95_seconds', group: 'cost_speed', format: 'seconds', colorDelta: true },
			{ name: 'total_prompt_tokens', group: 'cost_speed', format: 'int', colorDelta: false },
			{ name: 'total_completion_tokens', group: 'cost_speed', format: 'int', colorDelta: false }
		);
		return out;
	});

	function rawValue(run: EvalRunDetail, row: Row): number | null {
		if (row.name === 'weighted_score') return run.weighted_score?.score ?? null;
		if (row.group === 'cost_speed') {
			const dm = run.dashboard_metrics;
			return (dm?.[row.name as keyof typeof dm] as number | null | undefined) ?? null;
		}
		return run.scorecard?.metrics.find((m) => m.name === row.name)?.value ?? null;
	}

	function display(v: number | null, format: DeltaFormat): string {
		if (v == null) return '—';
		switch (format) {
			case 'pts':
				return `${(v * 100).toFixed(1)}%`;
			case 'usd':
				return `$${v.toFixed(4)}`;
			case 'seconds':
				return `${v.toFixed(2)}s`;
			case 'int':
				return v.toLocaleString();
		}
	}

	// A regression = worse than baseline A beyond epsilon, respecting metric direction.
	function isRegression(row: Row, delta: number | null): boolean {
		if (delta == null || !row.colorDelta) return false;
		const dir = getMetricThreshold(row.name).direction;
		const eps = EPS[row.format];
		return dir === 'higher' ? delta < -eps : delta > eps;
	}

	// Row is "unchanged" if every selected run is within epsilon of the spread.
	function isUnchanged(row: Row): boolean {
		if (!compareResult) return false;
		const vals = compareResult.runs.map((r) => rawValue(r, row)).filter((v): v is number => v != null);
		if (vals.length < 2) return false;
		return Math.max(...vals) - Math.min(...vals) <= EPS[row.format];
	}

	let visibleRows = $derived(hideUnchanged ? rows.filter((r) => !isUnchanged(r)) : rows);

	// ---- Trends across ALL runs (folds in the old Trends tab) -----------------
	let runsAsc = $derived.by(() =>
		[...runs].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
	);

	interface SparkCard {
		label: string;
		format: DeltaFormat;
		values: (number | null)[];
		latest: number | null;
	}

	let sparkCards = $derived.by((): SparkCard[] => {
		const pick = (fn: (r: EvalRunSummary) => number | null): (number | null)[] => runsAsc.map(fn);
		const cards: { label: string; format: DeltaFormat; values: (number | null)[] }[] = [
			{ label: 'Weighted score', format: 'pts', values: pick((r) => r.weighted_score) },
			{ label: 'Faithfulness', format: 'pts', values: pick((r) => r.metrics['faithfulness'] ?? null) },
			{ label: 'Answer correctness', format: 'pts', values: pick((r) => r.metrics['answer_correctness'] ?? null) },
			{
				label: 'Latency p95',
				format: 'seconds',
				values: pick((r) => (r.metrics['latency_p95_ms'] != null ? r.metrics['latency_p95_ms'] / 1000 : null))
			},
			{ label: 'Cost / query', format: 'usd', values: pick((r) => r.dashboard_metrics?.avg_cost_usd ?? null) }
		];
		return cards.map((c) => {
			const nonNull = c.values.filter((v): v is number => v != null);
			return { ...c, latest: nonNull.length ? nonNull[nonNull.length - 1] : null };
		});
	});

	onMount(loadRuns);

	async function loadRuns() {
		isLoading = true;
		error = null;
		try {
			const res = await fetchEvalRuns(50);
			runs = res.runs;
			if (selectedRunIds.length === 0 && runs.length >= 2) {
				selectedRunIds = runs.slice(0, 2).map((r) => r.id);
			}
			if (selectedRunIds.length >= 2) await loadComparison();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load data';
		} finally {
			isLoading = false;
		}
	}

	async function loadComparison() {
		if (selectedRunIds.length < 2) {
			compareResult = null;
			return;
		}
		isComparing = true;
		try {
			compareResult = await compareEvalRuns(orderedSelectedIds);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to compare runs';
		} finally {
			isComparing = false;
		}
	}

	function handleSelectionChange(ids: string[]) {
		selectedRunIds = ids;
		loadComparison();
	}
</script>

<div class="flex flex-col gap-3" class:animate-pulse={isLoading && runs.length === 0 && !error}>
	{#if error}
		<div class="alert alert-error text-sm py-2">
			<span>{error}</span>
			<button class="btn btn-xs" onclick={loadRuns}>Retry</button>
		</div>
	{/if}

	{#if !isLoading && runs.length === 0}
		<div class="term-panel border-l-4 border-l-base-content/20 text-sm">
			No eval runs yet — run an evaluation to compare configurations. Trigger one via POST /api/eval/runs or the evals CLI.
		</div>
	{/if}

	<!-- Layout always rendered (scaffold shows even with no runs) -->
	<!-- Trends: metric history across all runs -->
		<div class="term-panel">
			<div class="term-label mb-2 flex items-center gap-1">
				Metric history
				<InfoTip text="Each metric across all {runsAsc.length} runs, oldest → newest. Watch for regressions after a config change." />
			</div>
			<div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-2">
				{#each sparkCards as card}
					<div class="term-tile flex flex-col gap-1">
						<div class="term-label">{card.label}</div>
						<div class="font-mono tabular-nums text-lg">{display(card.latest, card.format)}</div>
						<MetricSparkline values={card.values} />
					</div>
				{/each}
			</div>
		</div>

		<!-- Controls -->
		<div class="flex items-center gap-3 flex-wrap">
			<span class="text-xs text-base-content/50">Baseline (A) = oldest selected run; Δ = column − A.</span>
			<label class="flex items-center gap-1.5 text-xs cursor-pointer">
				<input type="checkbox" class="checkbox checkbox-xs checkbox-primary" bind:checked={hideUnchanged} />
				Hide unchanged rows
			</label>
			<div class="flex-1 min-w-0"></div>
			<ExportButton runs={selectedSummaries} compare={compareResult ?? undefined} disabled={selectedSummaries.length === 0} />
			<button class="btn btn-sm btn-ghost" onclick={loadRuns}>Refresh</button>
		</div>

		<div class="grid grid-cols-1 lg:grid-cols-4 gap-3">
			<div class="lg:col-span-1">
				<RunSelector {runs} selected={selectedRunIds} onSelectionChange={handleSelectionChange} maxSelection={4} />
			</div>

			<div class="lg:col-span-3">
				{#if isComparing}
					<div class="flex items-center justify-center h-32"><span class="loading loading-spinner loading-md"></span></div>
				{:else if compareResult && rows.length > 0}
					<!-- Braintrust-style experiment columns -->
					<div class="term-panel overflow-x-auto">
						<div class="term-label mb-2 flex items-center gap-1">
							Experiment comparison
							<InfoTip text={panelDescription('compare_headline')} />
						</div>
						<table class="table table-xs term-table">
							<thead>
								<tr>
									<th>Metric</th>
									{#each compareResult.runs as run, i}
										<th class="text-right font-mono align-bottom">
											<div><span class="badge badge-ghost badge-xs mr-1">{RUN_LETTERS[i] ?? i + 1}</span>{run.name}</div>
											{#if run.config?.llm_model}
												<div class="font-normal text-base-content/40 normal-case">{run.config.llm_model}</div>
											{/if}
											{#if i === 0}<div class="text-[10px] text-base-content/40 normal-case">baseline</div>{/if}
										</th>
									{/each}
								</tr>
							</thead>
							<tbody>
								{#each visibleRows as row, ri}
									{@const desc = metricDescription(row.name)}
									{#if ri === 0 || visibleRows[ri - 1].group !== row.group}
										<tr><td colspan={compareResult.runs.length + 1} class="term-label pt-2">{GROUP_LABELS[row.group] ?? row.group}</td></tr>
									{/if}
									<tr class="hover" class:font-semibold={row.name === 'weighted_score'}>
										<td class="capitalize">
											<span class="inline-flex items-center gap-1">
												{metricLabel(row.name)}
												{#if desc}<InfoTip text={desc} />{/if}
											</span>
										</td>
										{#each compareResult.runs as run, i}
											{@const v = rawValue(run, row)}
											{@const base = rawValue(compareResult.runs[0], row)}
											{@const delta = i > 0 && v != null && base != null ? v - base : null}
											{@const regression = isRegression(row, delta)}
											<td class="text-right">
												<div class="inline-flex items-center justify-end gap-1">
													{#if regression}
														<span class="text-error" title="Regression vs baseline A" aria-label="regression">▼</span>
													{/if}
													<span class="term-num">{display(v, row.format)}</span>
												</div>
												{#if delta != null && Math.abs(delta) > EPS[row.format]}
													<div class="text-[10px] font-mono tabular-nums {row.colorDelta ? deltaColorClass(row.name, delta) : 'text-base-content/40'}">
														{formatDelta(delta, row.format)}
													</div>
												{/if}
											</td>
										{/each}
									</tr>
								{/each}
							</tbody>
						</table>
						{#if hideUnchanged && visibleRows.length < rows.length}
							<div class="text-center py-1 text-base-content/50 text-xs mt-1">
								{rows.length - visibleRows.length} unchanged rows hidden
							</div>
						{/if}
					</div>

					<!-- Config diff between baseline A and B -->
					{#if compareResult.runs.length >= 2}
						<div class="mt-3">
							<ConfigDiff
								configA={compareResult.runs[0].config}
								configB={compareResult.runs[1].config}
								labelA={`A · ${compareResult.runs[0].name}`}
								labelB={`B · ${compareResult.runs[1].name}`}
								showUnchanged={false}
							/>
						</div>
					{/if}
				{:else}
					<div class="term-panel flex items-center justify-center h-32 text-base-content/50 text-sm">
						Select at least two runs to compare.
					</div>
				{/if}
			</div>
		</div>
</div>
