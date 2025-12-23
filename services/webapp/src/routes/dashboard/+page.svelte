<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchSystemMetrics, type SystemMetrics } from '$lib/api';

	let metrics = $state<SystemMetrics | null>(null);
	let isLoading = $state(true);
	let error = $state<string | null>(null);
	let autoRefresh = $state(true);
	let refreshInterval: number | null = null;

	onMount(async () => {
		await loadMetrics();
		startAutoRefresh();

		return () => {
			stopAutoRefresh();
		};
	});

	function startAutoRefresh() {
		if (autoRefresh && !refreshInterval) {
			refreshInterval = window.setInterval(() => {
				loadMetrics();
			}, 30000); // Refresh every 30 seconds
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

	async function loadMetrics() {
		if (!autoRefresh && !isLoading) {
			isLoading = true;
		}
		error = null;
		try {
			metrics = await fetchSystemMetrics();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load metrics';
		} finally {
			isLoading = false;
		}
	}

	function getStatusColor(status: string): string {
		switch (status.toLowerCase()) {
			case 'healthy':
			case 'loaded':
			case 'available':
				return 'text-success';
			case 'unavailable':
			case 'unhealthy':
				return 'text-error';
			default:
				return 'text-warning';
		}
	}

	function getStatusBadge(status: string): string {
		switch (status.toLowerCase()) {
			case 'healthy':
			case 'loaded':
			case 'available':
				return 'badge-success';
			case 'unavailable':
			case 'unhealthy':
				return 'badge-error';
			default:
				return 'badge-warning';
		}
	}

	function formatPercent(value: number): string {
		return `${(value * 100).toFixed(1)}%`;
	}

	function formatBytes(bytes?: number): string {
		if (!bytes) return 'N/A';
		const mb = bytes / (1024 * 1024);
		return `${mb.toFixed(0)} MB`;
	}
</script>

{#if isLoading && !metrics}
	<div class="flex items-center justify-center h-[calc(100vh-200px)]">
		<span class="loading loading-spinner loading-lg"></span>
	</div>
{:else if error && !metrics}
	<div class="flex flex-col items-center justify-center h-[calc(100vh-200px)] gap-4">
		<div class="alert alert-error max-w-md">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				class="h-6 w-6 shrink-0"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
				/>
			</svg>
			<span>{error}</span>
		</div>
		<button class="btn btn-primary" onclick={loadMetrics}>Retry</button>
	</div>
{:else if metrics}
	<div class="flex flex-col gap-3">
		<!-- Compact Header -->
		<div class="bg-base-200 rounded-lg p-3 shadow-sm">
			<div class="flex items-center justify-between">
				<div class="flex items-center gap-4">
					<div>
						<h1 class="text-xl font-bold flex items-center gap-2">
							{metrics.system_name}
							<span class="text-xs font-normal text-base-content/50">v{metrics.version}</span>
						</h1>
						<p class="text-xs text-base-content/60">
							{new Date(metrics.timestamp).toLocaleString()}
						</p>
					</div>
					<div class="divider divider-horizontal mx-0"></div>
					<div class="flex items-center gap-2">
						<span
							class="h-2 w-2 rounded-full {metrics.health_status === 'healthy' ? 'bg-success animate-pulse' : 'bg-error'}"
						></span>
						<span class="text-sm font-medium capitalize">{metrics.health_status}</span>
					</div>
				</div>
				<div class="flex items-center gap-2">
					<button
						class="btn btn-ghost btn-xs"
						onclick={toggleAutoRefresh}
						title={autoRefresh ? 'Auto-refresh ON' : 'Auto-refresh OFF'}
					>
						<span class="text-xs">{autoRefresh ? '🔄' : '⏸️'}</span>
					</button>
					<button
						class="btn btn-ghost btn-xs"
						onclick={loadMetrics}
						disabled={isLoading}
						aria-label="Refresh metrics"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-3 w-3 {isLoading ? 'animate-spin' : ''}"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
							/>
						</svg>
					</button>
				</div>
			</div>
		</div>

		<!-- Key Metrics Row - Compact -->
		<div class="grid grid-cols-2 md:grid-cols-4 gap-3">
			<div class="bg-base-200 rounded-lg p-3 shadow-sm">
				<div class="text-xs text-base-content/60 mb-1">Documents</div>
				<div class="text-2xl font-bold text-primary">{metrics.document_count}</div>
				<div class="text-xs text-base-content/50">indexed</div>
			</div>
			<div class="bg-base-200 rounded-lg p-3 shadow-sm">
				<div class="text-xs text-base-content/60 mb-1">Chunks</div>
				<div class="text-2xl font-bold text-secondary">{metrics.chunk_count.toLocaleString()}</div>
				<div class="text-xs text-base-content/50">embeddings</div>
			</div>
			{#if metrics.latest_evaluation}
				<div class="bg-base-200 rounded-lg p-3 shadow-sm">
					<div class="text-xs text-base-content/60 mb-1">Pass Rate</div>
					<div class="text-2xl font-bold text-accent">
						{formatPercent(metrics.latest_evaluation.pass_rate)}
					</div>
					<div class="text-xs text-base-content/50">
						{metrics.latest_evaluation.passed_tests}/{metrics.latest_evaluation.total_tests} tests
					</div>
				</div>
				<div class="bg-base-200 rounded-lg p-3 shadow-sm">
					<div class="text-xs text-base-content/60 mb-1">Eval Framework</div>
					<div class="text-sm font-bold">{metrics.latest_evaluation.framework}</div>
					<div class="text-xs text-base-content/50 truncate" title={metrics.latest_evaluation.eval_model}>
						{metrics.latest_evaluation.eval_model}
					</div>
				</div>
			{/if}
		</div>

		<!-- Models Configuration - Data Dense Grid -->
		<div class="bg-base-200 rounded-lg p-3 shadow-sm">
			<h2 class="text-sm font-bold mb-3 flex items-center gap-2">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					class="h-4 w-4"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
					/>
				</svg>
				Models Configuration
			</h2>
			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2">
				<!-- LLM -->
				<div class="bg-base-100 rounded p-2 border border-base-300">
					<div class="flex items-center justify-between mb-1">
						<span class="text-xs font-semibold text-primary">LLM</span>
						<span class="badge badge-xs {getStatusBadge(metrics.models.llm.status)}"
							>{metrics.models.llm.status}</span
						>
					</div>
					<p class="font-mono text-xs font-bold truncate" title={metrics.models.llm.name}>
						{metrics.models.llm.name}
					</p>
					<div class="flex items-center justify-between mt-1">
						<span class="text-xs text-base-content/50">{metrics.models.llm.provider}</span>
						{#if metrics.models.llm.size?.parameters}
							<span class="text-xs text-base-content/50">{metrics.models.llm.size.parameters}</span>
						{/if}
					</div>
					{#if metrics.models.llm.size?.context_window}
						<div class="text-xs text-base-content/50 mt-0.5">
							ctx: {metrics.models.llm.size.context_window.toLocaleString()}
						</div>
					{/if}
					{#if metrics.models.llm.size?.disk_size_mb}
						<div class="text-xs text-base-content/50">
							{formatBytes(metrics.models.llm.size.disk_size_mb * 1024 * 1024)}
						</div>
					{/if}
				</div>

				<!-- Embedding -->
				<div class="bg-base-100 rounded p-2 border border-base-300">
					<div class="flex items-center justify-between mb-1">
						<span class="text-xs font-semibold text-secondary">Embedding</span>
						<span class="badge badge-xs {getStatusBadge(metrics.models.embedding.status)}"
							>{metrics.models.embedding.status}</span
						>
					</div>
					<p class="font-mono text-xs font-bold truncate" title={metrics.models.embedding.name}>
						{metrics.models.embedding.name}
					</p>
					<div class="flex items-center justify-between mt-1">
						<span class="text-xs text-base-content/50">{metrics.models.embedding.provider}</span>
						{#if metrics.models.embedding.size?.parameters}
							<span class="text-xs text-base-content/50"
								>{metrics.models.embedding.size.parameters}</span
							>
						{/if}
					</div>
					{#if metrics.models.embedding.size?.disk_size_mb}
						<div class="text-xs text-base-content/50">
							{formatBytes(metrics.models.embedding.size.disk_size_mb * 1024 * 1024)}
						</div>
					{/if}
				</div>

				<!-- Reranker -->
				{#if metrics.models.reranker}
					<div class="bg-base-100 rounded p-2 border border-base-300">
						<div class="flex items-center justify-between mb-1">
							<span class="text-xs font-semibold text-accent">Reranker</span>
							<span class="badge badge-xs {getStatusBadge(metrics.models.reranker.status)}"
								>{metrics.models.reranker.status}</span
							>
						</div>
						<p class="font-mono text-xs font-bold truncate" title={metrics.models.reranker.name}>
							{metrics.models.reranker.name}
						</p>
						<div class="flex items-center justify-between mt-1">
							<span class="text-xs text-base-content/50">{metrics.models.reranker.provider}</span>
							{#if metrics.models.reranker.size?.parameters}
								<span class="text-xs text-base-content/50"
									>{metrics.models.reranker.size.parameters}</span
								>
							{/if}
						</div>
						{#if metrics.models.reranker.size?.disk_size_mb}
							<div class="text-xs text-base-content/50">
								{formatBytes(metrics.models.reranker.size.disk_size_mb * 1024 * 1024)}
							</div>
						{/if}
					</div>
				{/if}

				<!-- Eval Model -->
				{#if metrics.models.eval}
					<div class="bg-base-100 rounded p-2 border border-base-300">
						<div class="flex items-center justify-between mb-1">
							<span class="text-xs font-semibold text-info">Eval</span>
							<span class="badge badge-xs {getStatusBadge(metrics.models.eval.status)}"
								>{metrics.models.eval.status}</span
							>
						</div>
						<p class="font-mono text-xs font-bold truncate" title={metrics.models.eval.name}>
							{metrics.models.eval.name}
						</p>
						<div class="flex items-center justify-between mt-1">
							<span class="text-xs text-base-content/50">{metrics.models.eval.provider}</span>
							{#if metrics.models.eval.size?.parameters}
								<span class="text-xs text-base-content/50">{metrics.models.eval.size.parameters}</span>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</div>

		<!-- Retrieval Pipeline - Compact -->
		<div class="bg-base-200 rounded-lg p-3 shadow-sm">
			<div class="flex items-center justify-between mb-3">
				<h2 class="text-sm font-bold flex items-center gap-2">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-4 w-4"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
						/>
					</svg>
					Retrieval Pipeline
				</h2>
				<div class="flex gap-2 text-xs">
					<span class="text-base-content/60">Top-K:</span>
					<span class="font-mono font-bold">{metrics.retrieval.retrieval_top_k}</span>
					<span class="text-base-content/60">→</span>
					<span class="text-base-content/60">Top-N:</span>
					<span class="font-mono font-bold">{metrics.retrieval.final_top_n}</span>
				</div>
			</div>

			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2">
				<!-- Hybrid Search -->
				<div class="bg-base-100 rounded p-2 border border-base-300">
					<div class="flex items-center justify-between mb-1">
						<span class="text-xs font-semibold">Hybrid Search</span>
						<span
							class="badge badge-xs {metrics.retrieval.hybrid_search.enabled ? 'badge-success' : 'badge-ghost'}"
						>
							{metrics.retrieval.hybrid_search.enabled ? 'ON' : 'OFF'}
						</span>
					</div>
					<p class="text-xs text-base-content/60 mb-1">
						{metrics.retrieval.hybrid_search.description}
					</p>
					{#if metrics.retrieval.hybrid_search.enabled}
						<div class="flex items-center gap-2 text-xs mt-1">
							<span class="text-base-content/50">RRF K:</span>
							<span class="font-mono font-bold">{metrics.retrieval.hybrid_search.rrf_k}</span>
						</div>
						<div class="badge badge-success badge-xs mt-1">
							{metrics.retrieval.hybrid_search.improvement_claim}
						</div>
					{/if}
				</div>

				<!-- BM25 -->
				<div class="bg-base-100 rounded p-2 border border-base-300">
					<div class="flex items-center justify-between mb-1">
						<span class="text-xs font-semibold">BM25 Sparse</span>
						<span
							class="badge badge-xs {metrics.retrieval.hybrid_search.bm25.enabled ? 'badge-success' : 'badge-ghost'}"
						>
							{metrics.retrieval.hybrid_search.bm25.enabled ? 'ON' : 'OFF'}
						</span>
					</div>
					<p class="text-xs text-base-content/60 mb-1">
						{metrics.retrieval.hybrid_search.bm25.description}
					</p>
					{#if metrics.retrieval.hybrid_search.bm25.enabled}
						<div class="flex flex-wrap gap-1 mt-1">
							{#each metrics.retrieval.hybrid_search.bm25.strengths as strength}
								<span class="badge badge-xs badge-outline">{strength}</span>
							{/each}
						</div>
					{/if}
				</div>

				<!-- Contextual Retrieval -->
				<div class="bg-base-100 rounded p-2 border border-base-300">
					<div class="flex items-center justify-between mb-1">
						<span class="text-xs font-semibold">Contextual</span>
						<span
							class="badge badge-xs {metrics.retrieval.contextual_retrieval.enabled ? 'badge-success' : 'badge-ghost'}"
						>
							{metrics.retrieval.contextual_retrieval.enabled ? 'ON' : 'OFF'}
						</span>
					</div>
					<p class="text-xs text-base-content/60 mb-1">
						{metrics.retrieval.contextual_retrieval.description}
					</p>
					{#if metrics.retrieval.contextual_retrieval.enabled}
						<div class="badge badge-success badge-xs mt-1">
							{metrics.retrieval.contextual_retrieval.improvement_claim}
						</div>
						<div class="badge badge-warning badge-xs mt-1">
							{metrics.retrieval.contextual_retrieval.performance_impact}
						</div>
					{/if}
				</div>

				<!-- Reranker -->
				<div class="bg-base-100 rounded p-2 border border-base-300">
					<div class="flex items-center justify-between mb-1">
						<span class="text-xs font-semibold">Reranker</span>
						<span
							class="badge badge-xs {metrics.retrieval.reranker.enabled ? 'badge-success' : 'badge-ghost'}"
						>
							{metrics.retrieval.reranker.enabled ? 'ON' : 'OFF'}
						</span>
					</div>
					<p class="text-xs text-base-content/60 mb-1">{metrics.retrieval.reranker.description}</p>
					{#if metrics.retrieval.reranker.enabled && metrics.retrieval.reranker.top_n}
						<div class="flex items-center gap-2 text-xs mt-1">
							<span class="text-base-content/50">Top-N:</span>
							<span class="font-mono font-bold">{metrics.retrieval.reranker.top_n}</span>
						</div>
					{/if}
				</div>
			</div>

			<div class="mt-2 text-xs text-base-content/60 font-mono">
				{metrics.retrieval.pipeline_description}
			</div>
		</div>

		<!-- Evaluation Metrics - Compact Grid -->
		{#if metrics.latest_evaluation}
			<div class="bg-base-200 rounded-lg p-3 shadow-sm">
				<div class="flex items-center justify-between mb-3">
					<h2 class="text-sm font-bold flex items-center gap-2">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-4 w-4"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
							/>
						</svg>
						Evaluation Metrics
						<span class="badge badge-outline badge-xs">{metrics.latest_evaluation.framework}</span>
					</h2>
					<div class="text-xs text-base-content/60">
						<span>Run: {metrics.latest_evaluation.run_id.slice(0, 8)}</span>
						<span class="mx-1">|</span>
						<span>{new Date(metrics.latest_evaluation.timestamp).toLocaleString()}</span>
					</div>
				</div>

				<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
					{#each Object.entries(metrics.latest_evaluation.metric_averages) as [name, score]}
						{@const passRate = metrics.latest_evaluation.metric_pass_rates[name] ?? 0}
						<div class="bg-base-100 rounded p-2 border border-base-300">
							<div class="text-xs text-base-content/60 mb-1 capitalize truncate" title={name}>
								{name.replace(/_/g, ' ')}
							</div>
							<div
								class="text-xl font-bold {score >= 0.7 ? 'text-success' : score >= 0.5 ? 'text-warning' : 'text-error'}"
							>
								{formatPercent(score)}
							</div>
							<div class="text-xs text-base-content/50">
								{formatPercent(passRate)} pass
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Component Health - Inline -->
		{#if Object.keys(metrics.component_status).length > 0}
			<div class="bg-base-200 rounded-lg p-3 shadow-sm">
				<h2 class="text-sm font-bold mb-2 flex items-center gap-2">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-4 w-4"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
						/>
					</svg>
					Component Health
				</h2>
				<div class="flex flex-wrap gap-2">
					{#each Object.entries(metrics.component_status) as [component, status]}
						<div class="flex items-center gap-2 bg-base-100 rounded px-2 py-1 border border-base-300">
							<span
								class="h-2 w-2 rounded-full {status === 'healthy' || status === 'available' ? 'bg-success animate-pulse' : 'bg-error'}"
							></span>
							<span class="text-xs font-medium capitalize">{component}</span>
							<span class="text-xs text-base-content/50">{status}</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</div>
{/if}
