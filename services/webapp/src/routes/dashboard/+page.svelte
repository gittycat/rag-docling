<script lang="ts">
	import { onMount } from 'svelte';
	import { getModelsInfo, getDocuments } from '$lib/utils/api';
	import type { ModelInfo, Document } from '$lib/utils/api';
	import {
		Activity,
		Database,
		FileText,
		HardDrive,
		Cpu,
		Layers,
		CheckCircle,
		XCircle,
		Server
	} from 'lucide-svelte';
	import { StatCard, AreaChart, PieChart, BarChart } from '$lib/components/charts';

	let modelsInfo = $state<ModelInfo | null>(null);
	let documents = $state<Document[]>([]);
	let isLoading = $state(true);
	let error = $state<string | null>(null);

	// Service health status (would come from API in production)
	let serviceStatus = $state({
		chromadb: 'healthy' as 'healthy' | 'unhealthy' | 'unknown',
		redis: 'healthy' as 'healthy' | 'unhealthy' | 'unknown',
		ollama: 'healthy' as 'healthy' | 'unhealthy' | 'unknown'
	});

	onMount(async () => {
		try {
			const [models, docs] = await Promise.all([getModelsInfo(), getDocuments()]);
			modelsInfo = models;
			documents = docs;

			// Check service health via API
			try {
				const healthRes = await fetch('/api/health');
				if (healthRes.ok) {
					const health = await healthRes.json();
					if (health.services) {
						serviceStatus = {
							chromadb: health.services.chromadb || 'unknown',
							redis: health.services.redis || 'unknown',
							ollama: health.services.ollama || 'unknown'
						};
					}
				}
			} catch {
				// Health check failed, keep defaults
			}
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to load system info';
		} finally {
			isLoading = false;
		}
	});

	function getTotalSize(): string {
		const totalBytes = documents.reduce((sum, doc) => sum + doc.file_size, 0);
		if (totalBytes < 1024) return `${totalBytes} B`;
		if (totalBytes < 1024 * 1024) return `${(totalBytes / 1024).toFixed(1)} KB`;
		return `${(totalBytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function getTotalChunks(): number {
		return documents.reduce((sum, doc) => sum + doc.node_count, 0);
	}

	// Generate document type distribution for pie chart
	const documentTypeData = $derived(() => {
		const typeCount: Record<string, number> = {};
		documents.forEach((doc) => {
			const ext = doc.file_name.split('.').pop()?.toUpperCase() || 'OTHER';
			typeCount[ext] = (typeCount[ext] || 0) + 1;
		});
		return Object.entries(typeCount)
			.map(([label, value]) => ({ label, value }))
			.sort((a, b) => b.value - a.value)
			.slice(0, 6);
	});

	// Generate chunks per document for bar chart
	const chunksPerDocData = $derived(() => {
		return documents
			.map((doc) => ({
				label:
					doc.file_name.length > 15 ? doc.file_name.slice(0, 12) + '...' : doc.file_name,
				value: doc.node_count
			}))
			.sort((a, b) => b.value - a.value)
			.slice(0, 8);
	});

	// Mock activity data for sparkline (would come from API)
	const activityData = $derived(() => {
		const now = new Date();
		return Array.from({ length: 7 }, (_, i) => ({
			date: new Date(now.getTime() - (6 - i) * 24 * 60 * 60 * 1000),
			value: Math.floor(Math.random() * 20) + 5
		}));
	});
</script>

<svelte:head>
	<title>RAG System - Dashboard</title>
</svelte:head>

<div class="p-6 space-y-6 max-w-7xl mx-auto">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold text-on-surface">System Dashboard</h1>

		<!-- Service Status Indicators -->
		<div class="flex gap-2">
			{#each Object.entries(serviceStatus) as [name, status]}
				<div
					class="flex items-center gap-1.5 px-3 py-1.5 bg-surface-raised rounded-full text-sm border border-default"
				>
					{#if status === 'healthy'}
						<CheckCircle class="w-3.5 h-3.5 text-green-500" />
					{:else if status === 'unhealthy'}
						<XCircle class="w-3.5 h-3.5 text-red-500" />
					{:else}
						<Server class="w-3.5 h-3.5 text-gray-400" />
					{/if}
					<span class="capitalize text-on-surface">{name}</span>
				</div>
			{/each}
		</div>
	</div>

	{#if isLoading}
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
			{#each Array(4) as _}
				<div class="bg-surface-raised rounded-lg p-4 border border-default animate-pulse h-28">
				</div>
			{/each}
		</div>
	{:else if error}
		<div class="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
			<p class="text-red-500">{error}</p>
		</div>
	{:else}
		<!-- Stats Cards Row -->
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
			<StatCard
				title="Documents"
				value={documents.length}
				icon={FileText}
				sparklineData={activityData()}
			/>
			<StatCard
				title="Total Chunks"
				value={getTotalChunks().toLocaleString()}
				icon={Layers}
				trend={documents.length > 0 ? 12 : undefined}
			/>
			<StatCard
				title="Embeddings"
				value={getTotalChunks().toLocaleString()}
				icon={Database}
				subtitle="Vector representations"
			/>
			<StatCard
				title="Storage"
				value={getTotalSize()}
				icon={HardDrive}
			/>
		</div>

		<!-- Charts Row -->
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
			<!-- Document Types Pie Chart -->
			<div class="bg-surface-raised rounded-lg p-6 border border-default">
				<h3 class="text-lg font-semibold text-on-surface mb-4">Document Types</h3>
				{#if documentTypeData().length > 0}
					<div class="flex justify-center">
						<PieChart data={documentTypeData()} donut showLabels />
					</div>
				{:else}
					<div class="flex items-center justify-center h-48 text-muted">
						No documents uploaded yet
					</div>
				{/if}
			</div>

			<!-- Chunks per Document Bar Chart -->
			<div class="bg-surface-raised rounded-lg p-6 border border-default">
				<h3 class="text-lg font-semibold text-on-surface mb-4">Chunks per Document</h3>
				{#if chunksPerDocData().length > 0}
					<BarChart data={chunksPerDocData()} height={220} />
				{:else}
					<div class="flex items-center justify-center h-48 text-muted">
						No documents uploaded yet
					</div>
				{/if}
			</div>
		</div>

		<!-- Models Info -->
		{#if modelsInfo}
			<div class="bg-surface-raised rounded-lg p-6 border border-default">
				<h2 class="text-lg font-semibold mb-4 text-on-surface flex items-center gap-2">
					<Cpu class="w-5 h-5" />
					Models in Use
				</h2>

				<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
					<div class="p-4 bg-surface-sunken rounded-lg">
						<h4 class="font-medium text-muted mb-1 text-sm">Language Model</h4>
						<p class="text-on-surface font-mono text-sm">{modelsInfo.llm_model}</p>
					</div>

					<div class="p-4 bg-surface-sunken rounded-lg">
						<h4 class="font-medium text-muted mb-1 text-sm">Embedding Model</h4>
						<p class="text-on-surface font-mono text-sm">{modelsInfo.embedding_model}</p>
					</div>

					{#if modelsInfo.reranker_model}
						<div class="p-4 bg-surface-sunken rounded-lg">
							<h4 class="font-medium text-muted mb-1 text-sm">Reranker Model</h4>
							<p class="text-on-surface font-mono text-sm">{modelsInfo.reranker_model}</p>
						</div>
					{/if}
				</div>
			</div>
		{/if}

		<!-- RAG Configuration -->
		<div class="bg-surface-raised rounded-lg p-6 border border-default">
			<h2 class="text-lg font-semibold mb-4 text-on-surface flex items-center gap-2">
				<Activity class="w-5 h-5" />
				RAG Configuration
			</h2>

			<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
				<div class="flex items-center justify-between p-3 bg-surface-sunken rounded-lg">
					<span class="text-sm text-muted">Hybrid Search</span>
					<span class="text-sm font-medium text-green-500">On</span>
				</div>
				<div class="flex items-center justify-between p-3 bg-surface-sunken rounded-lg">
					<span class="text-sm text-muted">Contextual Retrieval</span>
					<span class="text-sm font-medium text-yellow-500">Off</span>
				</div>
				<div class="flex items-center justify-between p-3 bg-surface-sunken rounded-lg">
					<span class="text-sm text-muted">Reranker</span>
					<span class="text-sm font-medium text-green-500">On</span>
				</div>
				<div class="flex items-center justify-between p-3 bg-surface-sunken rounded-lg">
					<span class="text-sm text-muted">Top-K</span>
					<span class="text-sm font-medium text-on-surface">10</span>
				</div>
			</div>
		</div>

		<!-- Tech Stack -->
		<div class="bg-surface-raised rounded-lg p-6 border border-default">
			<h2 class="text-lg font-semibold mb-4 text-on-surface">Tech Stack</h2>

			<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
				<div>
					<h3 class="font-semibold text-muted mb-2">Frontend</h3>
					<ul class="space-y-1 text-on-surface text-sm">
						<li>SvelteKit 2 + Svelte 5</li>
						<li>Tailwind CSS 4</li>
						<li>svelte-ux + LayerChart</li>
						<li>TypeScript</li>
					</ul>
				</div>

				<div>
					<h3 class="font-semibold text-muted mb-2">Backend</h3>
					<ul class="space-y-1 text-on-surface text-sm">
						<li>FastAPI + LlamaIndex</li>
						<li>Docling (Document Processing)</li>
						<li>ChromaDB + Redis + Celery</li>
						<li>Ollama (Local LLM)</li>
					</ul>
				</div>
			</div>
		</div>
	{/if}
</div>
