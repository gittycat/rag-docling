<script lang="ts">
	import type { EvalRunConfig } from '$lib/api/evals';
	import type { ModelsInfo, SystemMetrics } from '$lib/api';
	import InfoTip from './InfoTip.svelte';
	import { panelDescription } from '$lib/utils/metricInfo';

	interface Props {
		config: EvalRunConfig;
		/** Current system config — fills in chunking / RRF params the run config omits. */
		metrics?: SystemMetrics | null;
		/** Per-token cost rates from /models/info. */
		modelsInfo?: ModelsInfo | null;
	}

	let { config, metrics = null, modelsInfo = null }: Props = $props();

	// Rates describe the currently configured LLM. Showing them next to a run that
	// used a different model would misattribute the cost, so require a match.
	let rates = $derived.by(() => {
		if (!modelsInfo) return null;
		if (config.llm_model && config.llm_model !== modelsInfo.llm_model) return null;
		const { cost_per_1m_input_tokens: input, cost_per_1m_output_tokens: output } = modelsInfo;
		if (input === 0 && output === 0) return 'free (local)';
		return `$${input.toFixed(2)} in · $${output.toFixed(2)} out / 1M tok`;
	});

	function shortModel(name: string | null | undefined): string {
		if (!name) return '—';
		const parts = name.split('/');
		return parts[parts.length - 1];
	}

	interface Chip {
		label: string;
		value: string;
	}

	let chips = $derived.by((): Chip[] => {
		const r = metrics?.retrieval;
		const hs = r?.hybrid_search;
		// Prefer the run's own config; fall back to current system config so the
		// panel still shows "what would be measured" before any run exists.
		const llm = config.llm_model ?? metrics?.models?.llm?.name ?? null;
		const embed = config.embedding_model ?? metrics?.models?.embedding?.name ?? null;
		const rerank =
			config.reranker_model ??
			(r?.reranker?.enabled ? r.reranker.model ?? null : null);
		const topK = config.retrieval_top_k ?? r?.retrieval_top_k ?? null;
		const hybridOn = config.hybrid_search_enabled ?? hs?.enabled ?? false;
		const contextualOn = config.contextual_retrieval_enabled ?? r?.contextual_retrieval?.enabled ?? false;

		const list: Chip[] = [
			{ label: 'LLM', value: shortModel(llm) },
			{ label: 'embed', value: shortModel(embed) },
			{ label: 'rerank', value: rerank ? shortModel(rerank) : 'off' },
			{ label: 'top-k', value: topK != null ? String(topK) : '—' },
			{ label: 'hybrid', value: hybridOn ? (hs?.enabled ? `on · RRF k=${hs.rrf_k}` : 'on') : 'off' },
			{ label: 'contextual', value: contextualOn ? 'on' : 'off' }
		];
		const chunk = hs?.vector;
		if (chunk?.chunk_size != null) {
			list.push({ label: 'chunk', value: `${chunk.chunk_size}/${chunk.chunk_overlap}` });
		}
		return list;
	});
</script>

<div class="term-panel flex flex-wrap items-center gap-x-3 gap-y-1">
	<span class="term-label inline-flex items-center gap-1">
		Config under test
		<InfoTip text={panelDescription('config_snapshot')} />
	</span>
	{#each chips as chip}
		<span class="text-xs font-mono tabular-nums">
			<span class="text-base-content/50">{chip.label}</span>
			<span class="ml-1">{chip.value}</span>
		</span>
	{/each}
	{#if rates}
		<span class="text-xs font-mono tabular-nums inline-flex items-center gap-1">
			<span class="text-base-content/50">rates</span>
			<span>{rates}</span>
			<InfoTip text="Published token rates for the currently configured LLM, from /models/info. Multiply by the run's token counts to sanity-check cost per query." />
		</span>
	{/if}
</div>
