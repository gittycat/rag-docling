<script lang="ts">
	import { onMount } from 'svelte';
	import { getModelsInfo, getDocuments } from '$lib/utils/api';
	import type { ModelInfo, Document } from '$lib/utils/api';

	let modelsInfo = $state<ModelInfo | null>(null);
	let documents = $state<Document[]>([]);
	let isLoading = $state(true);
	let error = $state<string | null>(null);

	onMount(async () => {
		try {
			const [models, docs] = await Promise.all([getModelsInfo(), getDocuments()]);
			modelsInfo = models;
			documents = docs;
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to load system info';
		} finally {
			isLoading = false;
		}
	});

	function getTotalSize(): string {
		const totalBytes = documents.reduce((sum, doc) => sum + doc.file_size, 0);
		if (totalBytes < 1024 * 1024) {
			return `${(totalBytes / 1024).toFixed(2)} KB`;
		}
		return `${(totalBytes / (1024 * 1024)).toFixed(2)} MB`;
	}

	function getTotalChunks(): number {
		return documents.reduce((sum, doc) => sum + doc.node_count, 0);
	}
</script>

<svelte:head>
	<title>RAG System - About</title>
</svelte:head>

<div class="max-w-4xl mx-auto space-y-6">
	<div class="bg-white rounded-lg shadow-lg p-6">
		<h2 class="text-3xl font-bold mb-6">About RAG System</h2>

		<div class="prose max-w-none">
			<p class="text-gray-700 mb-4">
				This is a Retrieval-Augmented Generation (RAG) system that allows you to upload documents
				and query them using natural language. The system processes your documents, creates
				embeddings, and uses advanced retrieval techniques to find relevant information.
			</p>
		</div>
	</div>

	{#if isLoading}
		<div class="bg-white rounded-lg shadow-lg p-6">
			<div class="text-center py-8 text-gray-600">Loading system information...</div>
		</div>
	{:else if error}
		<div class="bg-white rounded-lg shadow-lg p-6">
			<div class="p-3 bg-red-100 border border-red-400 text-red-700 rounded">{error}</div>
		</div>
	{:else}
		<div class="bg-white rounded-lg shadow-lg p-6">
			<h3 class="text-2xl font-bold mb-4">Tech Stack</h3>

			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				<div class="space-y-3">
					<h4 class="font-semibold text-lg text-gray-700">Frontend</h4>
					<ul class="space-y-2 text-gray-600">
						<li class="flex items-center gap-2">
							<span class="w-2 h-2 bg-blue-600 rounded-full"></span>
							SvelteKit 2
						</li>
						<li class="flex items-center gap-2">
							<span class="w-2 h-2 bg-blue-600 rounded-full"></span>
							Svelte 5
						</li>
						<li class="flex items-center gap-2">
							<span class="w-2 h-2 bg-blue-600 rounded-full"></span>
							Tailwind CSS 4
						</li>
						<li class="flex items-center gap-2">
							<span class="w-2 h-2 bg-blue-600 rounded-full"></span>
							TypeScript
						</li>
					</ul>
				</div>

				<div class="space-y-3">
					<h4 class="font-semibold text-lg text-gray-700">Backend</h4>
					<ul class="space-y-2 text-gray-600">
						<li class="flex items-center gap-2">
							<span class="w-2 h-2 bg-green-600 rounded-full"></span>
							FastAPI
						</li>
						<li class="flex items-center gap-2">
							<span class="w-2 h-2 bg-green-600 rounded-full"></span>
							LlamaIndex
						</li>
						<li class="flex items-center gap-2">
							<span class="w-2 h-2 bg-green-600 rounded-full"></span>
							Docling (Document Processing)
						</li>
						<li class="flex items-center gap-2">
							<span class="w-2 h-2 bg-green-600 rounded-full"></span>
							ChromaDB (Vector Store)
						</li>
						<li class="flex items-center gap-2">
							<span class="w-2 h-2 bg-green-600 rounded-full"></span>
							Redis (Caching & Queue)
						</li>
						<li class="flex items-center gap-2">
							<span class="w-2 h-2 bg-green-600 rounded-full"></span>
							Celery (Async Processing)
						</li>
					</ul>
				</div>
			</div>
		</div>

		<div class="bg-white rounded-lg shadow-lg p-6">
			<h3 class="text-2xl font-bold mb-4">Models in Use</h3>

			<div class="space-y-4">
				{#if modelsInfo}
					<div class="p-4 bg-gray-50 rounded-lg">
						<h4 class="font-semibold text-gray-700 mb-2">Language Model (LLM)</h4>
						<p class="text-gray-600">{modelsInfo.llm_model}</p>
					</div>

					<div class="p-4 bg-gray-50 rounded-lg">
						<h4 class="font-semibold text-gray-700 mb-2">Embedding Model</h4>
						<p class="text-gray-600">{modelsInfo.embedding_model}</p>
					</div>

					{#if modelsInfo.reranker_model}
						<div class="p-4 bg-gray-50 rounded-lg">
							<h4 class="font-semibold text-gray-700 mb-2">Reranker Model</h4>
							<p class="text-gray-600">{modelsInfo.reranker_model}</p>
						</div>
					{/if}
				{/if}
			</div>
		</div>

		<div class="bg-white rounded-lg shadow-lg p-6">
			<h3 class="text-2xl font-bold mb-4">Document Statistics</h3>

			<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
				<div class="p-4 bg-blue-50 rounded-lg">
					<div class="text-3xl font-bold text-blue-600 mb-1">{documents.length}</div>
					<div class="text-gray-600">Documents Indexed</div>
				</div>

				<div class="p-4 bg-green-50 rounded-lg">
					<div class="text-3xl font-bold text-green-600 mb-1">{getTotalChunks()}</div>
					<div class="text-gray-600">Total Chunks</div>
				</div>

				<div class="p-4 bg-purple-50 rounded-lg">
					<div class="text-3xl font-bold text-purple-600 mb-1">{getTotalSize()}</div>
					<div class="text-gray-600">Total Size</div>
				</div>
			</div>
		</div>

		<div class="bg-white rounded-lg shadow-lg p-6">
			<h3 class="text-2xl font-bold mb-4">Features</h3>

			<ul class="space-y-3 text-gray-700">
				<li class="flex items-start gap-3">
					<span class="text-green-600 mt-1">✓</span>
					<span><strong>Hybrid Search:</strong> Combines BM25 (keyword) and vector (semantic) search with RRF fusion</span>
				</li>
				<li class="flex items-start gap-3">
					<span class="text-green-600 mt-1">✓</span>
					<span><strong>Contextual Retrieval:</strong> LLM-generated document context for improved retrieval accuracy</span>
				</li>
				<li class="flex items-start gap-3">
					<span class="text-green-600 mt-1">✓</span>
					<span><strong>Conversational Memory:</strong> Session-based chat history with Redis persistence</span>
				</li>
				<li class="flex items-start gap-3">
					<span class="text-green-600 mt-1">✓</span>
					<span><strong>Async Processing:</strong> Background document processing with real-time progress tracking</span>
				</li>
				<li class="flex items-start gap-3">
					<span class="text-green-600 mt-1">✓</span>
					<span><strong>Multiple Formats:</strong> Supports PDF, DOCX, PPTX, XLSX, TXT, MD, HTML, and more</span>
				</li>
			</ul>
		</div>
	{/if}
</div>
