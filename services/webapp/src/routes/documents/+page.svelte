<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import FileUpload from '$lib/components/FileUpload.svelte';
	import DocumentTable from '$lib/components/DocumentTable.svelte';
	import LoadingSkeleton from '$lib/components/feedback/LoadingSkeleton.svelte';
	import { documentsStore } from '$lib/stores/documents';
	import { getDocuments, getBatchStatus } from '$lib/utils/api';

	let pollingInterval: ReturnType<typeof setInterval> | null = null;

	onMount(async () => {
		await loadDocuments();
		startPolling();
	});

	onDestroy(() => {
		stopPolling();
	});

	async function loadDocuments() {
		documentsStore.setLoading(true);
		try {
			const docs = await getDocuments();
			documentsStore.setDocuments(docs);
		} catch (error) {
			documentsStore.setError(
				error instanceof Error ? error.message : 'Failed to load documents'
			);
		} finally {
			documentsStore.setLoading(false);
		}
	}

	function handleUploadStart(batchId: string) {
		documentsStore.addUploadingBatch(batchId, {
			batch_id: batchId,
			total: 0,
			completed: 0,
			total_chunks: 0,
			completed_chunks: 0,
			tasks: {}
		});
		pollBatchStatus(batchId);
	}

	async function pollBatchStatus(batchId: string) {
		try {
			const status = await getBatchStatus(batchId);
			documentsStore.updateBatchStatus(batchId, status);

			if (status.completed === status.total) {
				documentsStore.removeBatch(batchId);
				await loadDocuments();
			}
		} catch (error) {
			console.error('Failed to poll batch status:', error);
		}
	}

	function startPolling() {
		pollingInterval = setInterval(async () => {
			const batches = $documentsStore.uploadingBatches;
			if (batches.size > 0) {
				for (const batchId of batches.keys()) {
					await pollBatchStatus(batchId);
				}
			}
		}, 2000);
	}

	function stopPolling() {
		if (pollingInterval) {
			clearInterval(pollingInterval);
			pollingInterval = null;
		}
	}
</script>

<svelte:head>
	<title>RAG System - Documents</title>
</svelte:head>

<div class="p-6 space-y-6">
	<div class="bg-surface-raised rounded-lg shadow-lg p-6 border border-default">
		<h2 class="text-2xl font-bold mb-4 text-on-surface">Document Management</h2>

		<FileUpload onUploadStart={handleUploadStart} />

		{#if $documentsStore.error}
			<div class="mt-4 p-3 bg-red-900/20 border border-red-500/50 text-red-400 rounded">
				{$documentsStore.error}
			</div>
		{/if}
	</div>

	<div class="bg-surface-raised rounded-lg shadow-lg p-6 border border-default">
		<h3 class="text-xl font-bold mb-4 text-on-surface">Documents</h3>

		{#if $documentsStore.isLoading}
			<LoadingSkeleton rows={5} height="h-12" />
		{:else}
			<DocumentTable uploadingBatches={$documentsStore.uploadingBatches} />
		{/if}
	</div>
</div>
