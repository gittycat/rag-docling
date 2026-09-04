<script lang="ts">
	import type { RetrievalFunnel } from '$lib/api/evals';
	import InfoTip from './InfoTip.svelte';

	interface Props {
		funnel: RetrievalFunnel | null | undefined;
	}

	let { funnel }: Props = $props();

	// Human-readable stage names. bm25 and vector run in parallel over the same
	// query; fusion combines them; rerank reorders what fusion produced.
	const STAGE_LABEL: Record<string, string> = {
		bm25: 'BM25 (keyword)',
		vector: 'Vector (dense)',
		fusion: 'Fused (RRF)',
		rerank: 'Reranked'
	};

	let stages = $derived(funnel?.stages.filter((s) => s.recall != null) ?? []);
	let measured = $derived(funnel != null && funnel.final != null);

	function pct(v: number | null | undefined): string {
		return v != null ? `${(v * 100).toFixed(1)}%` : '—';
	}

	function signedPct(v: number | null): string {
		return v != null ? `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%` : '';
	}

	// A stage that loses recall is the interesting one; gains are expected at fusion.
	function deltaClass(v: number | null): string {
		if (v == null) return 'text-base-content/30';
		if (v < -0.02) return 'text-error';
		if (v > 0.02) return 'text-success';
		return 'text-base-content/50';
	}
</script>

<div class="term-panel flex flex-col gap-3">
	<div class="flex items-center justify-between gap-2">
		<span class="term-label inline-flex items-center gap-1">
			Retrieval funnel
			<InfoTip
				text="Recall@5 measured separately at each pipeline stage, against the same gold evidence. Each stage can only pass on what the one before it found, so the drop between stages is where the evidence was lost. This is the diagnostic to read before changing anything about retrieval."
			/>
		</span>
		{#if measured}
			<span class="font-mono tabular-nums text-sm">{pct(funnel?.final)} final recall</span>
		{/if}
	</div>

	{#if !measured}
		<div class="py-3 text-xs text-base-content/50">
			{funnel?.note ?? 'awaiting a run with retrieval ground truth'}
		</div>
	{:else}
		<div class="flex flex-col gap-1.5">
			{#each stages as stage (stage.name)}
				<div class="flex items-center gap-2">
					<span class="w-28 shrink-0 text-xs text-base-content/70">
						{STAGE_LABEL[stage.name] ?? stage.name}
					</span>
					<div class="h-3 flex-1 overflow-hidden rounded-sm bg-base-300/60">
						<div
							class="h-full {stage.name === 'rerank' ? 'bg-primary' : 'bg-primary/50'}"
							style="width: {((stage.recall ?? 0) * 100).toFixed(1)}%"
						></div>
					</div>
					<span class="w-14 shrink-0 text-right font-mono text-xs tabular-nums">
						{pct(stage.recall)}
					</span>
					<span
						class="w-14 shrink-0 text-right font-mono text-[10px] tabular-nums {deltaClass(
							stage.delta
						)}"
					>
						{signedPct(stage.delta)}
					</span>
				</div>
			{/each}
		</div>

		<!-- The two halves of total loss. They point at opposite halves of the system,
		     which is the whole reason for splitting them. -->
		<div class="grid grid-cols-2 gap-2 border-t border-base-300/60 pt-2">
			<div>
				<div class="term-label text-[10px]">Never retrieved</div>
				<div class="font-mono text-lg tabular-nums">{pct(funnel?.lost_before_candidates)}</div>
				<div class="text-[10px] text-base-content/50">absent from the candidate list</div>
			</div>
			<div>
				<div class="term-label text-[10px]">Dropped by rerank</div>
				<div class="font-mono text-lg tabular-nums">{pct(funnel?.lost_in_rerank)}</div>
				<div class="text-[10px] text-base-content/50">retrieved, then ranked out</div>
			</div>
		</div>

		{#if funnel?.fusion_lift != null}
			<div class="font-mono text-[10px] text-base-content/50">
				Fusion lift over the better leg (nDCG@10): {funnel.fusion_lift >= 0 ? '+' : ''}{funnel.fusion_lift.toFixed(
					3
				)}
			</div>
		{/if}

		{#if funnel?.diagnosis}
			<div
				class="rounded-sm border-l-2 px-2 py-1.5 text-xs {funnel.bottleneck
					? 'border-warning bg-warning/5'
					: 'border-success bg-success/5'}"
			>
				{funnel.diagnosis}
			</div>
		{/if}
	{/if}
</div>
