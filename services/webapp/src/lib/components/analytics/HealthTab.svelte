<script lang="ts">
	import { untrack } from 'svelte';
	import { fetchModelsInfo, type ModelsInfo, type SystemMetrics } from '$lib/api';
	import {
		fetchEvalRuns,
		fetchEvalRun,
		type EvalRunDetail,
		type EvalRunSummary
	} from '$lib/api/evals';
	import {
		computeBracketHealth,
		computeWeakestLink,
		weakestLinkVerdict,
		type Bracket,
		type BandedMetric,
		type Health
	} from '$lib/utils/stageHealth';
	import { deltaColorClass } from '$lib/utils/thresholds';
	import { formatDelta, metricLabel, metricDescription } from '$lib/utils/metricInfo';
	import StatPanel from './StatPanel.svelte';
	import LatencyPanel from './LatencyPanel.svelte';
	import MetricBreakdown from './MetricBreakdown.svelte';
	import ConfigContext from './ConfigContext.svelte';
	import RetrievalFunnel from './RetrievalFunnel.svelte';

	interface Props {
		metrics: SystemMetrics;
		refreshTick?: number;
	}

	let { metrics, refreshTick = 0 }: Props = $props();

	let detail = $state<EvalRunDetail | null>(null);
	let modelsInfo = $state<ModelsInfo | null>(null);
	let prev = $state<EvalRunSummary | null>(null);
	let hasRuns = $state<boolean | null>(null); // null = not yet loaded
	let firstLoad = $state(true);
	let error = $state<string | null>(null);

	$effect(() => {
		void refreshTick;
		untrack(() => load());
	});

	async function load() {
		error = null;
		try {
			// Cost rates are supplementary — never fail the panel over them.
			fetchModelsInfo()
				.then((info) => (modelsInfo = info))
				.catch(() => (modelsInfo = null));

			const res = await fetchEvalRuns(2);
			if (res.runs.length === 0) {
				hasRuns = false;
				detail = null;
				prev = null;
			} else {
				hasRuns = true;
				prev = res.runs[1] ?? null;
				detail = await fetchEvalRun(res.runs[0].id);
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load health data';
		} finally {
			firstLoad = false;
		}
	}

	let bracketHealth = $derived(computeBracketHealth(detail));
	let weakest = $derived(computeWeakestLink(bracketHealth));

	let verdict = $derived.by(() => {
		if (!detail?.scorecard?.metrics?.length) {
			return 'No eval runs yet — start one from the Experiments tab to populate these panels.';
		}
		return weakestLinkVerdict(detail, bracketHealth, weakest);
	});

	let bannerBorderClass = $derived.by(() => {
		if (!detail?.scorecard?.metrics?.length) return 'border-l-base-content/20';
		if (!weakest) return 'border-l-success';
		return weakest.band === 'bad' ? 'border-l-error' : 'border-l-warning';
	});

	// ---- Stat panel values ---------------------------------------------------

	let funnel = $derived(detail?.retrieval_funnel ?? null);
	let funnelDelta = $derived(
		funnel?.final != null && prev?.retrieval_funnel?.final != null
			? funnel.final - prev.retrieval_funnel.final
			: null
	);
	const BOTTLENECK_LABEL: Record<string, string> = {
		ingestion: 'Ingestion',
		rerank: 'Reranker'
	};
	let bottleneckLabel = $derived(
		funnel?.final == null ? '—' : (BOTTLENECK_LABEL[funnel.bottleneck ?? ''] ?? 'None')
	);

	let cost = $derived(detail?.dashboard_metrics?.avg_cost_usd ?? null);
	let costDelta = $derived(
		cost != null && prev?.dashboard_metrics?.avg_cost_usd != null
			? cost - prev.dashboard_metrics.avg_cost_usd
			: null
	);

	let p95 = $derived(detail?.dashboard_metrics?.latency_p95_seconds ?? null);
	let p95Delta = $derived(
		p95 != null && prev?.dashboard_metrics?.latency_p95_seconds != null
			? p95 - prev.dashboard_metrics.latency_p95_seconds
			: null
	);

	function driver(bracket: Bracket): BandedMetric | null {
		const banded = bracketHealth[bracket].banded;
		if (banded.length === 0) return null;
		const rank: Record<string, number> = { good: 1, warn: 2, bad: 3, unknown: 0 };
		return [...banded].sort((a, b) => rank[b.band] - rank[a.band] || b.deviation - a.deviation)[0];
	}

	function driverDelta(d: BandedMetric | null): number | null {
		if (!d || !prev) return null;
		const p = prev.metrics[d.metric.name];
		const current = d.metric.value;
		// Either side undefined means there is no delta to state, not a delta of 0
		return p != null && current != null ? current - p : null;
	}

	let retrievalDriver = $derived(driver('retrieval'));
	let generationDriver = $derived(driver('generation'));

	function pct(v: number | null | undefined): string {
		return v != null ? `${(v * 100).toFixed(1)}%` : '—';
	}
	function usd(v: number | null | undefined): string {
		return v != null ? `$${v.toFixed(4)}` : '—';
	}
	function secs(v: number | null | undefined): string {
		return v != null ? `${v.toFixed(2)}s` : '—';
	}

	// Subtle skeleton pulse only during the very first fetch.
	let skeleton = $derived(firstLoad && hasRuns === null && !error);
</script>

<div class="flex flex-col gap-3" class:animate-pulse={skeleton}>
	{#if error}
		<div class="alert alert-error text-sm py-2">
			<span>{error}</span>
			<button class="btn btn-xs" onclick={load}>Retry</button>
		</div>
	{/if}

	<!-- Weakest-link verdict (always present) -->
	<div class="term-panel border-l-4 {bannerBorderClass}">
		<p class="text-sm">{verdict}</p>
	</div>

	<!-- Stat panels: most-critical top-left. Rendered even with no data (values '—'). -->
	<div class="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2">
		<StatPanel
			label="Retrieval recall"
			tip="Recall@5 of what the model actually saw — the last stage of the retrieval funnel. Nothing downstream can answer from evidence that never got here."
			value={pct(funnel?.final ?? null)}
			health={bracketHealth.retrieval.health}
			showBadge
			emphasis
			delta={funnelDelta != null ? `${formatDelta(funnelDelta, 'pts')} vs prev` : null}
			deltaClass={deltaColorClass('recall_at_5', funnelDelta)}
		>
			{#if funnel?.ceiling != null}
				<div class="text-[10px] font-mono text-base-content/50">
					ceiling {pct(funnel.ceiling)}
				</div>
			{/if}
		</StatPanel>

		<StatPanel
			label="Retrieval bottleneck"
			tip="Which half of the system is losing the evidence: ingestion (it was never retrieved) or the reranker (it was retrieved, then ranked out)."
			value={bottleneckLabel}
			health={funnel?.bottleneck ? 'warn' : funnel?.final != null ? 'good' : 'unknown'}
			showBadge
		>
			{#if retrievalDriver}
				<div class="text-[10px] font-mono text-base-content/50">weakest: {metricLabel(retrievalDriver.metric.name)}</div>
			{/if}
		</StatPanel>

		<StatPanel
			label="Generation"
			value={generationDriver ? pct(generationDriver.metric.value) : '—'}
			health={bracketHealth.generation.health}
			showBadge
			delta={generationDriver && driverDelta(generationDriver) != null
				? `${formatDelta(driverDelta(generationDriver)!, 'pts')} vs prev`
				: null}
			deltaClass={generationDriver ? deltaColorClass(generationDriver.metric.name, driverDelta(generationDriver)) : ''}
		>
			{#if generationDriver}
				<div class="text-[10px] font-mono text-base-content/50">weakest: {metricLabel(generationDriver.metric.name)}</div>
			{/if}
		</StatPanel>

		<StatPanel
			label="Cost / query"
			tip={metricDescription('avg_cost_usd')}
			value={usd(cost)}
			delta={costDelta != null ? `${formatDelta(costDelta, 'usd')} vs prev` : null}
			deltaClass={deltaColorClass('avg_cost_usd', costDelta)}
		/>

		<StatPanel
			label="Latency p95"
			tip={metricDescription('latency_p95_ms')}
			value={secs(p95)}
			delta={p95Delta != null ? `${formatDelta(p95Delta, 'seconds')} vs prev` : null}
			deltaClass={deltaColorClass('latency_p95_seconds', p95Delta)}
		/>
	</div>

	<!-- Where the evidence was lost: the diagnostic that names what to change -->
	<RetrievalFunnel {funnel} />

	<!-- Config context: what is being measured (system config exists even with no runs) -->
	<ConfigContext config={detail?.config ?? {}} {metrics} {modelsInfo} />

	<!-- Latency distribution (honest degrade of the "waterfall") -->
	<LatencyPanel {detail} />

	<!-- Full metric breakdown by group -->
	<MetricBreakdown {detail} {bracketHealth} />
</div>
