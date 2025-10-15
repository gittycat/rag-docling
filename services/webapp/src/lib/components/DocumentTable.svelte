<script lang="ts">
	import { documentsStore } from '$lib/stores/documents';
	import { deleteDocument } from '$lib/utils/api';
	import type { Document, BatchStatus } from '$lib/utils/api';

	interface Props {
		uploadingBatches: Map<string, BatchStatus>;
	}

	let { uploadingBatches }: Props = $props();

	let confirmDelete = $state<string | null>(null);

	async function handleDelete(documentId: string) {
		if (confirmDelete !== documentId) {
			confirmDelete = documentId;
			return;
		}

		try {
			await deleteDocument(documentId);
			documentsStore.removeDocument(documentId);
			confirmDelete = null;
		} catch (error) {
			console.error('Failed to delete document:', error);
			alert('Failed to delete document: ' + (error instanceof Error ? error.message : 'Unknown error'));
		}
	}

	function formatFileSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
	}

	function getFileExtension(fileName: string): string {
		const parts = fileName.split('.');
		return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : 'unknown';
	}

	function getProgressPercentage(task: any): number {
		if (!task.total_chunks || task.total_chunks === 0) return 0;
		return Math.round((task.completed_chunks / task.total_chunks) * 100);
	}
</script>

<div class="overflow-x-auto">
	<table class="w-full border-collapse">
		<thead>
			<tr class="bg-gray-200">
				<th class="px-4 py-3 text-left">Document Name</th>
				<th class="px-4 py-3 text-left">Type</th>
				<th class="px-4 py-3 text-left">Size</th>
				<th class="px-4 py-3 text-left">Status</th>
				<th class="px-4 py-3 text-left">Actions</th>
			</tr>
		</thead>
		<tbody>
			<!-- Documents being uploaded/processed -->
			{#each Array.from(uploadingBatches.values()) as batch}
				{#each Object.values(batch.tasks) as task}
					<tr class="border-b hover:bg-gray-50">
						<td class="px-4 py-3">{task.file_name}</td>
						<td class="px-4 py-3">{getFileExtension(task.file_name)}</td>
						<td class="px-4 py-3">-</td>
						<td class="px-4 py-3">
							{#if task.status === 'failed'}
								<span class="text-red-600">Failed: {task.error || 'Unknown error'}</span>
							{:else if task.status === 'completed'}
								<span class="text-green-600">Completed</span>
							{:else}
								<div class="flex flex-col gap-1">
									<span class="text-blue-600">
										{task.status === 'pending' ? 'Pending' : 'Processing'}
									</span>
									{#if task.total_chunks && task.total_chunks > 0}
										<div class="w-full bg-gray-200 rounded-full h-2">
											<div
												class="bg-blue-600 h-2 rounded-full transition-all"
												style="width: {getProgressPercentage(task)}%"
											></div>
										</div>
										<span class="text-xs text-gray-600">
											{task.completed_chunks || 0} / {task.total_chunks} chunks
										</span>
									{/if}
								</div>
							{/if}
						</td>
						<td class="px-4 py-3">-</td>
					</tr>
				{/each}
			{/each}

			<!-- Indexed documents -->
			{#each $documentsStore.documents as doc}
				<tr class="border-b hover:bg-gray-50">
					<td class="px-4 py-3">{doc.file_name}</td>
					<td class="px-4 py-3">{doc.file_type}</td>
					<td class="px-4 py-3">{formatFileSize(doc.file_size)}</td>
					<td class="px-4 py-3">
						<span class="text-green-600">Indexed ({doc.node_count} chunks)</span>
					</td>
					<td class="px-4 py-3">
						<button
							onclick={() => handleDelete(doc.document_id)}
							class="px-3 py-1 rounded transition"
							class:bg-red-600={confirmDelete === doc.document_id}
							class:text-white={confirmDelete === doc.document_id}
							class:hover:bg-red-700={confirmDelete === doc.document_id}
							class:bg-red-100={confirmDelete !== doc.document_id}
							class:text-red-600={confirmDelete !== doc.document_id}
							class:hover:bg-red-200={confirmDelete !== doc.document_id}
						>
							{confirmDelete === doc.document_id ? 'Click to confirm' : 'Delete'}
						</button>
					</td>
				</tr>
			{/each}

			{#if $documentsStore.documents.length === 0 && uploadingBatches.size === 0}
				<tr>
					<td colspan="5" class="px-4 py-8 text-center text-gray-500">
						No documents yet. Upload some files to get started.
					</td>
				</tr>
			{/if}
		</tbody>
	</table>
</div>
