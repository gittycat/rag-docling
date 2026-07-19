<script lang="ts">
	import { BarChart } from 'layerchart';
	import type { EvalRunDetail } from '$lib/api/evals';
	import InfoTip from './InfoTip.svelte';

	interface Props {
		detail: EvalRunDetail | null;
	}

	let { detail }: Props = $props();

	interface LatBar {
		stage: string;
		seconds: number;
	}

	// HONEST DEGRADE: the eval harness times each query end-to-end only
	// (services/evals/evals/runner.py — a single perf_counter around the whole
	// query). There is no retrieval-vs-generation or per-stage split in the data,
	// so instead of fabricating a stage waterfall we show the real end-to-end
	// latency distribution (p50 / avg / p95), labelled as such.
	let d = $derived(detail?.dashboard_metrics ?? null);

	let bars = $derived.by((): LatBar[] => {
		if (!d) return [];
		const rows: LatBar[] = [];
		if (d.latency_p50_seconds != null) rows.push({ stage: 'p50', seconds: d.latency_p50_seconds });
		if (d.latency_avg_seconds != null) rows.push({ stage: 'avg', seconds: d.latency_avg_seconds });
		if (d.latency_p95_seconds != null) rows.push({ stage: 'p95', seconds: d.latency_p95_seconds });
		return rows;
	});

	let hasData = $derived(bars.length > 0);
	function fmt(v: number | null | undefined): string {
		return v != null ? `${v.toFixed(2)}s` : '—';
	}
</script>

<div class="term-panel flex flex-col gap-2">
	<div class="flex items-center justify-between">
		<span class="term-label inline-flex items-center gap-1">
			End-to-end latency
			<InfoTip
				text="Query latency is measured end-to-end only — the eval harness does not capture per-stage (retrieval vs. generation) timings, so this shows the p50 / average / p95 distribution rather than a stage waterfall."
			/>
		</span>
		<span class="text-[10px] font-mono text-base-content/40 uppercase tracking-wider">seconds</span>
	</div>

	{#if !hasData}
		<!-- Scaffold: keep the row structure visible so a first-time viewer sees what will populate here -->
		<div class="h-28 flex flex-col justify-center gap-2 px-1">
			{#each ['p50', 'avg', 'p95'] as row}
				<div class="flex items-center gap-2">
					<span class="w-8 text-[10px] font-mono text-base-content/40">{row}</span>
					<div class="flex-1 h-3 bg-base-300/40 rounded-sm"></div>
				</div>
			{/each}
		</div>
		<div class="flex items-center gap-4 text-xs font-mono tabular-nums text-base-content/40">
			<span>p50 —</span><span>avg —</span><span>p95 —</span>
			<span class="text-[10px]">awaiting first run</span>
		</div>
	{:else}
		<div class="h-28">
			<BarChart
				data={bars}
				x="seconds"
				y="stage"
				orientation="horizontal"
				series={[{ key: 'seconds', value: 'seconds', color: 'var(--color-primary)' }]}
				grid={false}
				bandPadding={0.3}
				padding={{ left: 34, right: 16, top: 2, bottom: 18 }}
				props={{ bars: { radius: 2 } }}
			/>
		</div>
		<!-- Numbers surfaced explicitly (the chart tooltip is hover-only) -->
		<div class="flex items-center gap-4 text-xs font-mono tabular-nums">
			<span><span class="text-base-content/50">p50</span> {fmt(d?.latency_p50_seconds)}</span>
			<span><span class="text-base-content/50">avg</span> {fmt(d?.latency_avg_seconds)}</span>
			<span class="text-warning"><span class="text-base-content/50">p95</span> {fmt(d?.latency_p95_seconds)}</span>
			<span class="text-base-content/40 text-[10px]">p95 = slow tail (1 in 20 queries)</span>
		</div>
	{/if}
</div>
