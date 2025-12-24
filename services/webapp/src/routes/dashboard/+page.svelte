<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchSystemMetrics,
		fetchEvaluationSummary,
		fetchDocuments,
		type SystemMetrics,
		type EvaluationSummary,
		type Document
	} from '$lib/api';
	import Sparkline from '$lib/components/Sparkline.svelte';

	let metrics = $state<SystemMetrics | null>(null);
	let evalSummary = $state<EvaluationSummary | null>(null);
	let documents = $state<Document[]>([]);
	let isLoading = $state(true);
	let error = $state<string | null>(null);
	let autoRefresh = $state(true);
	let refreshInterval: number | null = null;

	onMount(async () => {
		await loadAll();
		startAutoRefresh();
		return () => stopAutoRefresh();
	});

	function startAutoRefresh() {
		if (autoRefresh && !refreshInterval) {
			refreshInterval = window.setInterval(() => loadAll(), 30000);
		}
	}

	function stopAutoRefresh() {
		if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			startAutoRefresh();
		} else {
			stopAutoRefresh();
		}
	}

	async function loadAll() {
		if (!autoRefresh && !isLoading) isLoading = true;
		error = null;
		try {
			const [m, e, d] = await Promise.all([
				fetchSystemMetrics(),
				fetchEvaluationSummary().catch(() => null),
				fetchDocuments().catch(() => [])
			]);
			metrics = m;
			evalSummary = e;
			documents = d;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load data';
		} finally {
			isLoading = false;
		}
	}

	function getStatusBadge(status: string): string {
		const s = status.toLowerCase();
		if (['healthy', 'loaded', 'available'].includes(s)) return 'badge-success';
		if (['unavailable', 'unhealthy'].includes(s)) return 'badge-error';
		return 'badge-warning';
	}

	function getScoreColor(score: number): string {
		if (score >= 0.7) return 'text-success';
		if (score >= 0.5) return 'text-warning';
		return 'text-error';
	}

	function getTrendColor(direction: string): string {
		if (direction === 'improving') return 'oklch(var(--su))';
		if (direction === 'declining') return 'oklch(var(--er))';
		return 'oklch(var(--wa))';
	}

	function getTrendIcon(direction: string): string {
		if (direction === 'improving') return '↑';
		if (direction === 'declining') return '↓';
		return '→';
	}

	function formatPercent(value: number): string {
		return `${(value * 100).toFixed(1)}%`;
	}

	function formatSize(mb?: number): string {
		if (!mb) return '-';
		if (mb >= 1024) return `${(mb / 1024).toFixed(1)}G`;
		return `${mb.toFixed(0)}M`;
	}

	function timeAgo(timestamp: string): string {
		const diff = Date.now() - new Date(timestamp).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	function getModelsArray(models: SystemMetrics['models']) {
		const arr = [
			{ type: 'LLM', ...models.llm },
			{ type: 'Embed', ...models.embedding }
		];
		if (models.reranker) arr.push({ type: 'Rerank', ...models.reranker });
		if (models.eval) arr.push({ type: 'Eval', ...models.eval });
		return arr;
	}
</script>

{#if isLoading && !metrics}
	<div class="flex items-center justify-center h-[calc(100vh-200px)]">
		<span class="loading loading-spinner loading-lg"></span>
	</div>
{:else if error && !metrics}
	<div class="flex flex-col items-center justify-center h-[calc(100vh-200px)] gap-4">
		<div class="alert alert-error max-w-md">
			<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
			</svg>
			<span>{error}</span>
		</div>
		<button class="btn btn-primary btn-sm" onclick={loadAll}>Retry</button>
	</div>
{:else if metrics}
	<div class="flex flex-col gap-2">
		<!-- Header Bar -->
		<div class="bg-base-200 rounded px-3 py-2 flex items-center justify-between text-xs">
			<div class="flex items-center gap-3">
				<span class="font-bold text-sm">{metrics.system_name}</span>
				<span class="text-base-content/50">v{metrics.version}</span>
				<div class="divider divider-horizontal mx-0 h-4"></div>
				<span class="flex items-center gap-1">
					<span class="h-2 w-2 rounded-full {metrics.health_status === 'healthy' ? 'bg-success animate-pulse' : 'bg-error'}"></span>
					<span class="capitalize">{metrics.health_status}</span>
				</span>
				<div class="divider divider-horizontal mx-0 h-4"></div>
				<span><strong>{metrics.document_count}</strong> docs</span>
				<span><strong>{metrics.chunk_count.toLocaleString()}</strong> chunks</span>
			</div>
			<div class="flex items-center gap-1">
				<span class="text-base-content/50">{new Date(metrics.timestamp).toLocaleTimeString()}</span>
				<button class="btn btn-ghost btn-xs" onclick={toggleAutoRefresh} title={autoRefresh ? 'Auto-refresh ON' : 'Auto-refresh OFF'}>
					{autoRefresh ? '🔄' : '⏸️'}
				</button>
				<button class="btn btn-ghost btn-xs" onclick={loadAll} disabled={isLoading} aria-label="Refresh">
					<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 {isLoading ? 'animate-spin' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
					</svg>
				</button>
			</div>
		</div>

		<!-- Component Health -->
		{#if Object.keys(metrics.component_status).length > 0}
			<div class="flex items-center gap-2 px-1">
				<span class="text-xs text-base-content/50">Services:</span>
				{#each Object.entries(metrics.component_status) as [name, status]}
					<div class="tooltip" data-tip="{name}: {status}">
						<span class="flex items-center gap-1 text-xs bg-base-200 rounded px-1.5 py-0.5">
							<span class="h-1.5 w-1.5 rounded-full {status === 'healthy' || status === 'available' ? 'bg-success' : 'bg-error'}"></span>
							<span class="capitalize">{name}</span>
						</span>
					</div>
				{/each}
			</div>
		{/if}

		<!-- Models Table -->
		<div class="bg-base-200 rounded p-2">
			<div class="text-xs font-semibold mb-1 text-base-content/70">Models</div>
			<div class="overflow-x-auto">
				<table class="table table-xs w-full">
					<thead>
						<tr class="text-xs">
							<th class="py-1">Type</th>
							<th class="py-1">Model</th>
							<th class="py-1">Provider</th>
							<th class="py-1">Params</th>
							<th class="py-1">Size</th>
							<th class="py-1">Status</th>
						</tr>
					</thead>
					<tbody>
						{#each getModelsArray(metrics.models) as model}
							<tr class="hover">
								<td class="py-1 font-semibold text-primary">{model.type}</td>
								<td class="py-1 font-mono text-xs truncate max-w-[150px]" title={model.name}>{model.name}</td>
								<td class="py-1">{model.provider}</td>
								<td class="py-1">{model.size?.parameters ?? '-'}</td>
								<td class="py-1">{formatSize(model.size?.disk_size_mb)}</td>
								<td class="py-1"><span class="badge badge-xs {getStatusBadge(model.status)}">{model.status}</span></td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>

		<!-- Retrieval Pipeline -->
		<div class="bg-base-200 rounded p-2">
			<div class="text-xs font-semibold mb-1 text-base-content/70">Retrieval Pipeline</div>
			<div class="flex flex-wrap items-center gap-1 text-xs">
				<span class="bg-base-100 rounded px-2 py-1 font-mono">Query</span>
				<span class="text-base-content/50">→</span>
				<span class="bg-base-100 rounded px-2 py-1 flex items-center gap-1">
					Hybrid
					<span class="badge badge-xs {metrics.retrieval.hybrid_search.enabled ? 'badge-success' : 'badge-ghost'}">
						{metrics.retrieval.hybrid_search.enabled ? 'ON' : 'OFF'}
					</span>
				</span>
				{#if metrics.retrieval.hybrid_search.enabled}
					<span class="text-base-content/50">→</span>
					<span class="bg-base-100 rounded px-2 py-1">
						BM25+Vec <span class="text-base-content/50">RRF k={metrics.retrieval.hybrid_search.rrf_k}</span>
					</span>
				{/if}
				<span class="text-base-content/50">→</span>
				<span class="bg-base-100 rounded px-2 py-1 flex items-center gap-1">
					Rerank
					<span class="badge badge-xs {metrics.retrieval.reranker.enabled ? 'badge-success' : 'badge-ghost'}">
						{metrics.retrieval.reranker.enabled ? 'ON' : 'OFF'}
					</span>
					{#if metrics.retrieval.reranker.enabled && metrics.retrieval.reranker.top_n}
						<span class="text-base-content/50">top-{metrics.retrieval.reranker.top_n}</span>
					{/if}
				</span>
				<span class="text-base-content/50">→</span>
				<span class="bg-base-100 rounded px-2 py-1 font-mono">LLM</span>
				<div class="divider divider-horizontal mx-1 h-4"></div>
				<span class="text-base-content/50">Top-K:</span>
				<span class="font-mono font-bold">{metrics.retrieval.retrieval_top_k}</span>
				<span class="text-base-content/50">→ Top-N:</span>
				<span class="font-mono font-bold">{metrics.retrieval.final_top_n}</span>
				<div class="divider divider-horizontal mx-1 h-4"></div>
				<span class="flex items-center gap-1">
					Contextual
					<span class="badge badge-xs {metrics.retrieval.contextual_retrieval.enabled ? 'badge-success' : 'badge-ghost'}">
						{metrics.retrieval.contextual_retrieval.enabled ? 'ON' : 'OFF'}
					</span>
				</span>
			</div>
		</div>

		<!-- Evaluation Metrics with Sparklines -->
		{#if evalSummary && evalSummary.metric_trends.length > 0}
			<div class="bg-base-200 rounded p-2">
				<div class="flex items-center justify-between mb-1">
					<div class="text-xs font-semibold text-base-content/70">Evaluation Metrics</div>
					<div class="text-xs text-base-content/50">
						{#if evalSummary.latest_run}
							<span class="badge badge-outline badge-xs mr-1">{evalSummary.latest_run.framework}</span>
							{timeAgo(evalSummary.latest_run.timestamp)} · {evalSummary.total_runs} runs
						{/if}
					</div>
				</div>
				<div class="grid grid-cols-5 gap-2">
					{#each evalSummary.metric_trends as trend}
						<div class="bg-base-100 rounded p-1.5 text-center">
							<div class="text-xs text-base-content/60 truncate capitalize" title={trend.metric_name}>
								{trend.metric_name.replace(/_/g, ' ')}
							</div>
							<div class="text-lg font-bold {getScoreColor(trend.latest_value)}">
								{formatPercent(trend.latest_value)}
							</div>
							<div class="flex items-center justify-center gap-1">
								<Sparkline values={trend.values} strokeColor={getTrendColor(trend.trend_direction)} />
								<span class="text-xs {trend.trend_direction === 'improving' ? 'text-success' : trend.trend_direction === 'declining' ? 'text-error' : 'text-warning'}">
									{getTrendIcon(trend.trend_direction)}
								</span>
							</div>
						</div>
					{/each}
				</div>
				{#if evalSummary.latest_run}
					<div class="flex items-center gap-3 mt-2 text-xs text-base-content/60">
						<span>Pass: <strong class="text-base-content">{evalSummary.latest_run.passed_tests}/{evalSummary.latest_run.total_tests}</strong> ({formatPercent(evalSummary.latest_run.pass_rate)})</span>
						<span>Eval model: <span class="font-mono">{evalSummary.latest_run.eval_model}</span></span>
					</div>
				{/if}
			</div>
		{:else if metrics.latest_evaluation}
			<!-- Fallback: show latest_evaluation from system metrics if no summary -->
			<div class="bg-base-200 rounded p-2">
				<div class="flex items-center justify-between mb-1">
					<div class="text-xs font-semibold text-base-content/70">Evaluation Metrics</div>
					<div class="text-xs text-base-content/50">
						<span class="badge badge-outline badge-xs mr-1">{metrics.latest_evaluation.framework}</span>
						{timeAgo(metrics.latest_evaluation.timestamp)}
					</div>
				</div>
				<div class="grid grid-cols-5 gap-2">
					{#each Object.entries(metrics.latest_evaluation.metric_averages) as [name, score]}
						<div class="bg-base-100 rounded p-1.5 text-center">
							<div class="text-xs text-base-content/60 truncate capitalize" title={name}>
								{name.replace(/_/g, ' ')}
							</div>
							<div class="text-lg font-bold {getScoreColor(score)}">
								{formatPercent(score)}
							</div>
							<div class="text-xs text-base-content/50">
								{formatPercent(metrics.latest_evaluation.metric_pass_rates[name] ?? 0)} pass
							</div>
						</div>
					{/each}
				</div>
				<div class="flex items-center gap-3 mt-2 text-xs text-base-content/60">
					<span>Pass: <strong class="text-base-content">{metrics.latest_evaluation.passed_tests}/{metrics.latest_evaluation.total_tests}</strong> ({formatPercent(metrics.latest_evaluation.pass_rate)})</span>
					<span>Eval model: <span class="font-mono">{metrics.latest_evaluation.eval_model}</span></span>
				</div>
			</div>
		{/if}

		<!-- Recent Documents -->
		{#if documents.length > 0}
			<div class="bg-base-200 rounded p-2">
				<div class="flex items-center justify-between mb-1">
					<div class="text-xs font-semibold text-base-content/70">Recent Documents</div>
					<a href="/documents" class="text-xs link link-primary">View all →</a>
				</div>
				<div class="overflow-x-auto">
					<table class="table table-xs w-full">
						<thead>
							<tr class="text-xs">
								<th class="py-1">Filename</th>
								<th class="py-1 text-right">Chunks</th>
							</tr>
						</thead>
						<tbody>
							{#each documents.slice(0, 5) as doc}
								<tr class="hover">
									<td class="py-1 font-mono text-xs truncate max-w-[300px]" title={doc.file_name}>{doc.file_name}</td>
									<td class="py-1 text-right">{doc.chunks}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}
	</div>
{/if}
