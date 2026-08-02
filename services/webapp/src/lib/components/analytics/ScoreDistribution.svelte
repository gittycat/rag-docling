<script lang="ts">
	interface Props {
		/** Per-question scores from MetricResult.details.individual_scores. */
		scores: number[];
		bins?: number;
	}

	let { scores, bins = 10 }: Props = $props();

	let sorted = $derived([...scores].sort((a, b) => a - b));

	let stats = $derived.by(() => {
		if (sorted.length === 0) return null;
		const at = (q: number) => sorted[Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1)))];
		return {
			n: sorted.length,
			min: sorted[0],
			p25: at(0.25),
			median: at(0.5),
			p75: at(0.75),
			max: sorted[sorted.length - 1]
		};
	});

	// Scores are 0..1; the last bin is closed so a perfect 1.0 is not dropped.
	let histogram = $derived.by(() => {
		const counts = new Array(bins).fill(0) as number[];
		for (const s of scores) {
			const clamped = Math.max(0, Math.min(1, s));
			const idx = Math.min(bins - 1, Math.floor(clamped * bins));
			counts[idx] += 1;
		}
		const max = Math.max(1, ...counts);
		return counts.map((count, i) => ({
			count,
			height: count / max,
			from: i / bins,
			to: (i + 1) / bins
		}));
	});

	function pct(v: number): string {
		return `${(v * 100).toFixed(0)}%`;
	}
</script>

{#if stats}
	<div class="flex flex-col gap-1">
		<div class="flex items-end gap-[2px] h-12" role="img" aria-label="Score distribution across {stats.n} questions">
			{#each histogram as bar}
				<div
					class="flex-1 bg-primary/60 rounded-t-[1px] min-h-[1px]"
					style="height: {(bar.height * 100).toFixed(1)}%"
					title="{pct(bar.from)}–{pct(bar.to)}: {bar.count} question{bar.count === 1 ? '' : 's'}"
				></div>
			{/each}
		</div>
		<div class="flex justify-between text-[10px] font-mono text-base-content/40">
			<span>0%</span>
			<span>100%</span>
		</div>
		<div class="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] font-mono tabular-nums text-base-content/60">
			<span>n={stats.n}</span>
			<span>min {pct(stats.min)}</span>
			<span>p25 {pct(stats.p25)}</span>
			<span>median {pct(stats.median)}</span>
			<span>p75 {pct(stats.p75)}</span>
			<span>max {pct(stats.max)}</span>
		</div>
	</div>
{:else}
	<div class="text-[10px] text-base-content/40">no per-question scores</div>
{/if}
