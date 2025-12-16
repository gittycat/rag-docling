<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchSystemMetrics, type SystemMetrics } from '$lib/api';

	let metrics = $state<SystemMetrics | null>(null);
	let isLoading = $state(true);
	let error = $state<string | null>(null);

	onMount(async () => {
		await loadMetrics();
	});

	async function loadMetrics() {
		isLoading = true;
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
</script>

{#if isLoading}
	<div class="flex items-center justify-center h-[calc(100vh-200px)]">
		<span class="loading loading-spinner loading-lg"></span>
	</div>
{:else if error}
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
	<div class="flex flex-col gap-6">
		<!-- Header -->
		<div class="flex items-center justify-between">
			<div>
				<h1 class="text-2xl font-bold">{metrics.system_name}</h1>
				<p class="text-base-content/60">v{metrics.version}</p>
			</div>
			<div class="flex items-center gap-2">
				<span class="badge {getStatusBadge(metrics.health_status)} badge-lg gap-2">
					<span
						class="h-2 w-2 rounded-full {metrics.health_status === 'healthy' ? 'bg-success' : 'bg-error'}"
					></span>
					{metrics.health_status}
				</span>
				<button class="btn btn-ghost btn-sm" onclick={loadMetrics} aria-label="Refresh metrics">
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
							d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
						/>
					</svg>
				</button>
			</div>
		</div>

		<!-- Stats Cards -->
		<div class="stats shadow bg-base-200">
			<div class="stat">
				<div class="stat-figure text-primary">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-8 w-8"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
						/>
					</svg>
				</div>
				<div class="stat-title">Documents</div>
				<div class="stat-value text-primary">{metrics.document_count}</div>
				<div class="stat-desc">Indexed in ChromaDB</div>
			</div>

			<div class="stat">
				<div class="stat-figure text-secondary">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-8 w-8"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"
						/>
					</svg>
				</div>
				<div class="stat-title">Chunks</div>
				<div class="stat-value text-secondary">{metrics.chunk_count.toLocaleString()}</div>
				<div class="stat-desc">Vector embeddings</div>
			</div>

			{#if metrics.latest_evaluation}
				<div class="stat">
					<div class="stat-figure text-accent">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-8 w-8"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
							/>
						</svg>
					</div>
					<div class="stat-title">Pass Rate</div>
					<div class="stat-value text-accent">{formatPercent(metrics.latest_evaluation.pass_rate)}</div>
					<div class="stat-desc">{metrics.latest_evaluation.passed_tests}/{metrics.latest_evaluation.total_tests} tests passed</div>
				</div>
			{/if}
		</div>

		<!-- Models Section -->
		<div class="card bg-base-200 shadow">
			<div class="card-body">
				<h2 class="card-title">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-5 w-5"
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
					Models
				</h2>

				<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
					<!-- LLM -->
					<div class="bg-base-100 rounded-lg p-4">
						<div class="flex items-center justify-between mb-2">
							<span class="text-sm font-semibold text-base-content/60">LLM</span>
							<span class="badge badge-sm {getStatusBadge(metrics.models.llm.status)}"
								>{metrics.models.llm.status}</span
							>
						</div>
						<p class="font-mono text-sm">{metrics.models.llm.name}</p>
						<p class="text-xs text-base-content/50">{metrics.models.llm.provider}</p>
						{#if metrics.models.llm.size?.parameters}
							<p class="text-xs text-base-content/50">{metrics.models.llm.size.parameters} parameters</p>
						{/if}
					</div>

					<!-- Embedding -->
					<div class="bg-base-100 rounded-lg p-4">
						<div class="flex items-center justify-between mb-2">
							<span class="text-sm font-semibold text-base-content/60">Embedding</span>
							<span class="badge badge-sm {getStatusBadge(metrics.models.embedding.status)}"
								>{metrics.models.embedding.status}</span
							>
						</div>
						<p class="font-mono text-sm">{metrics.models.embedding.name}</p>
						<p class="text-xs text-base-content/50">{metrics.models.embedding.provider}</p>
					</div>

					<!-- Reranker -->
					{#if metrics.models.reranker}
						<div class="bg-base-100 rounded-lg p-4">
							<div class="flex items-center justify-between mb-2">
								<span class="text-sm font-semibold text-base-content/60">Reranker</span>
								<span class="badge badge-sm {getStatusBadge(metrics.models.reranker.status)}"
									>{metrics.models.reranker.status}</span
								>
							</div>
							<p class="font-mono text-sm truncate" title={metrics.models.reranker.name}
								>{metrics.models.reranker.name}</p
							>
							<p class="text-xs text-base-content/50">{metrics.models.reranker.provider}</p>
						</div>
					{/if}
				</div>
			</div>
		</div>

		<!-- Retrieval Pipeline Section -->
		<div class="card bg-base-200 shadow">
			<div class="card-body">
				<h2 class="card-title">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-5 w-5"
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
				<p class="text-sm text-base-content/60 font-mono">{metrics.retrieval.pipeline_description}</p>

				<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
					<!-- Hybrid Search -->
					<div class="bg-base-100 rounded-lg p-4">
						<div class="flex items-center justify-between mb-2">
							<span class="text-sm font-semibold">Hybrid Search</span>
							<span
								class="badge badge-sm {metrics.retrieval.hybrid_search.enabled ? 'badge-success' : 'badge-ghost'}"
							>
								{metrics.retrieval.hybrid_search.enabled ? 'ON' : 'OFF'}
							</span>
						</div>
						<p class="text-xs text-base-content/60">{metrics.retrieval.hybrid_search.description}</p>
						{#if metrics.retrieval.hybrid_search.enabled}
							<div class="mt-2 text-xs">
								<span class="text-base-content/50">RRF K:</span>
								<span class="font-mono">{metrics.retrieval.hybrid_search.rrf_k}</span>
							</div>
							<p class="text-xs text-success mt-1">{metrics.retrieval.hybrid_search.improvement_claim}</p>
						{/if}
					</div>

					<!-- BM25 -->
					<div class="bg-base-100 rounded-lg p-4">
						<div class="flex items-center justify-between mb-2">
							<span class="text-sm font-semibold">BM25</span>
							<span
								class="badge badge-sm {metrics.retrieval.hybrid_search.bm25.enabled ? 'badge-success' : 'badge-ghost'}"
							>
								{metrics.retrieval.hybrid_search.bm25.enabled ? 'ON' : 'OFF'}
							</span>
						</div>
						<p class="text-xs text-base-content/60">
							{metrics.retrieval.hybrid_search.bm25.description}
						</p>
						{#if metrics.retrieval.hybrid_search.bm25.enabled}
							<div class="mt-2">
								{#each metrics.retrieval.hybrid_search.bm25.strengths as strength}
									<span class="badge badge-xs badge-outline mr-1 mb-1">{strength}</span>
								{/each}
							</div>
						{/if}
					</div>

					<!-- Contextual Retrieval -->
					<div class="bg-base-100 rounded-lg p-4">
						<div class="flex items-center justify-between mb-2">
							<span class="text-sm font-semibold">Contextual</span>
							<span
								class="badge badge-sm {metrics.retrieval.contextual_retrieval.enabled ? 'badge-success' : 'badge-ghost'}"
							>
								{metrics.retrieval.contextual_retrieval.enabled ? 'ON' : 'OFF'}
							</span>
						</div>
						<p class="text-xs text-base-content/60">
							{metrics.retrieval.contextual_retrieval.description}
						</p>
						{#if metrics.retrieval.contextual_retrieval.enabled}
							<p class="text-xs text-success mt-1">
								{metrics.retrieval.contextual_retrieval.improvement_claim}
							</p>
							<p class="text-xs text-warning mt-1">
								{metrics.retrieval.contextual_retrieval.performance_impact}
							</p>
						{/if}
					</div>

					<!-- Reranker -->
					<div class="bg-base-100 rounded-lg p-4">
						<div class="flex items-center justify-between mb-2">
							<span class="text-sm font-semibold">Reranker</span>
							<span
								class="badge badge-sm {metrics.retrieval.reranker.enabled ? 'badge-success' : 'badge-ghost'}"
							>
								{metrics.retrieval.reranker.enabled ? 'ON' : 'OFF'}
							</span>
						</div>
						<p class="text-xs text-base-content/60">{metrics.retrieval.reranker.description}</p>
						{#if metrics.retrieval.reranker.enabled && metrics.retrieval.reranker.top_n}
							<div class="mt-2 text-xs">
								<span class="text-base-content/50">Top-N:</span>
								<span class="font-mono">{metrics.retrieval.reranker.top_n}</span>
							</div>
						{/if}
					</div>
				</div>

				<!-- Retrieval Parameters -->
				<div class="flex gap-4 mt-4">
					<div class="text-sm">
						<span class="text-base-content/50">Initial Top-K:</span>
						<span class="font-mono font-bold">{metrics.retrieval.retrieval_top_k}</span>
					</div>
					<div class="text-sm">
						<span class="text-base-content/50">Final Top-N:</span>
						<span class="font-mono font-bold">{metrics.retrieval.final_top_n}</span>
					</div>
				</div>
			</div>
		</div>

		<!-- Latest Evaluation Section -->
		{#if metrics.latest_evaluation}
			<div class="card bg-base-200 shadow">
				<div class="card-body">
					<h2 class="card-title">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-5 w-5"
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
						Latest Evaluation
						<span class="badge badge-outline badge-sm ml-2">{metrics.latest_evaluation.framework}</span>
					</h2>

					<div class="text-sm text-base-content/60 mb-4">
						<span>Run ID: {metrics.latest_evaluation.run_id}</span>
						<span class="mx-2">|</span>
						<span>Model: {metrics.latest_evaluation.eval_model}</span>
						<span class="mx-2">|</span>
						<span>{new Date(metrics.latest_evaluation.timestamp).toLocaleString()}</span>
					</div>

					<!-- Metric Averages -->
					<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
						{#each Object.entries(metrics.latest_evaluation.metric_averages) as [name, score]}
							{@const passRate = metrics.latest_evaluation.metric_pass_rates[name] ?? 0}
							<div class="bg-base-100 rounded-lg p-3 text-center">
								<p class="text-xs text-base-content/60 mb-1 capitalize">
									{name.replace(/_/g, ' ')}
								</p>
								<p class="text-xl font-bold {score >= 0.7 ? 'text-success' : score >= 0.5 ? 'text-warning' : 'text-error'}">
									{formatPercent(score)}
								</p>
								<p class="text-xs text-base-content/50">
									{formatPercent(passRate)} pass rate
								</p>
							</div>
						{/each}
					</div>
				</div>
			</div>
		{/if}

		<!-- Component Health -->
		{#if Object.keys(metrics.component_status).length > 0}
			<div class="card bg-base-200 shadow">
				<div class="card-body">
					<h2 class="card-title">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-5 w-5"
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
							<div class="flex items-center gap-2 bg-base-100 rounded-lg px-3 py-2">
								<span
									class="h-2 w-2 rounded-full {status === 'healthy' || status === 'available' ? 'bg-success' : 'bg-error'}"
								></span>
								<span class="text-sm font-medium capitalize">{component}</span>
								<span class="text-xs text-base-content/50">{status}</span>
							</div>
						{/each}
					</div>
				</div>
			</div>
		{/if}
	</div>
{/if}
