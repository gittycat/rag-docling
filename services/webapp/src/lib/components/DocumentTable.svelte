<script lang="ts">
	import { documentsStore } from '$lib/stores/documents';
	import { deleteDocument } from '$lib/utils/api';
	import { toast } from '$lib/stores/toast.svelte';
	import ConfirmDialog from '$lib/components/feedback/ConfirmDialog.svelte';
	import type { Document, BatchStatus } from '$lib/utils/api';
	import { ArrowUpDown, Search, FileText, Upload } from 'lucide-svelte';

	interface Props {
		uploadingBatches: Map<string, BatchStatus>;
	}

	let { uploadingBatches }: Props = $props();

	type SortKey = 'name' | 'type' | 'size' | 'chunks';
	type SortDirection = 'asc' | 'desc';

	let sortKey = $state<SortKey>('name');
	let sortDirection = $state<SortDirection>('asc');
	let searchQuery = $state('');
	let deleteDialogOpen = $state(false);
	let documentToDelete = $state<Document | null>(null);

	function handleSort(key: SortKey) {
		if (sortKey === key) {
			sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
		} else {
			sortKey = key;
			sortDirection = 'asc';
		}
	}

	const filteredAndSortedDocs = $derived(() => {
		let docs = $documentsStore.documents;

		// Filter
		if (searchQuery.trim()) {
			const query = searchQuery.toLowerCase();
			docs = docs.filter((doc) =>
				doc.file_name.toLowerCase().includes(query) ||
				doc.file_type.toLowerCase().includes(query)
			);
		}

		// Sort
		docs = [...docs].sort((a, b) => {
			let valA: string | number;
			let valB: string | number;

			switch (sortKey) {
				case 'name':
					valA = a.file_name.toLowerCase();
					valB = b.file_name.toLowerCase();
					break;
				case 'type':
					valA = a.file_type.toLowerCase();
					valB = b.file_type.toLowerCase();
					break;
				case 'size':
					valA = a.file_size;
					valB = b.file_size;
					break;
				case 'chunks':
					valA = a.node_count;
					valB = b.node_count;
					break;
			}

			if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
			if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
			return 0;
		});

		return docs;
	});

	function openDeleteDialog(doc: Document) {
		documentToDelete = doc;
		deleteDialogOpen = true;
	}

	function cancelDelete() {
		deleteDialogOpen = false;
		documentToDelete = null;
	}

	async function confirmDelete() {
		if (!documentToDelete) return;

		const docId = documentToDelete.document_id;
		const fileName = documentToDelete.file_name;

		try {
			await deleteDocument(docId);
			documentsStore.removeDocument(docId);
			toast.success(`Deleted "${fileName}"`);
		} catch (error) {
			const message = error instanceof Error ? error.message : 'Unknown error';
			toast.error(`Failed to delete "${fileName}": ${message}`);
		} finally {
			deleteDialogOpen = false;
			documentToDelete = null;
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

<!-- Search bar -->
<div class="mb-4">
	<div class="relative">
		<Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
		<input
			type="text"
			bind:value={searchQuery}
			placeholder="Search documents..."
			class="w-full pl-10 pr-4 py-2 bg-surface-raised border border-default rounded-lg
						 text-on-surface placeholder:text-muted focus:outline-none focus:ring-2
						 focus:ring-primary/50 transition"
		/>
	</div>
</div>

<div class="overflow-x-auto">
	<table class="w-full border-collapse">
		<thead>
			<tr class="bg-surface-sunken">
				<th class="px-4 py-3 text-left">
					<button
						onclick={() => handleSort('name')}
						class="flex items-center gap-2 text-on-surface font-medium hover:text-primary transition"
					>
						Document Name
						<ArrowUpDown class="w-4 h-4" />
					</button>
				</th>
				<th class="px-4 py-3 text-left">
					<button
						onclick={() => handleSort('type')}
						class="flex items-center gap-2 text-on-surface font-medium hover:text-primary transition"
					>
						Type
						<ArrowUpDown class="w-4 h-4" />
					</button>
				</th>
				<th class="px-4 py-3 text-left">
					<button
						onclick={() => handleSort('size')}
						class="flex items-center gap-2 text-on-surface font-medium hover:text-primary transition"
					>
						Size
						<ArrowUpDown class="w-4 h-4" />
					</button>
				</th>
				<th class="px-4 py-3 text-left text-on-surface font-medium">Status</th>
				<th class="px-4 py-3 text-left text-on-surface font-medium">Actions</th>
			</tr>
		</thead>
		<tbody>
			<!-- Documents being uploaded/processed -->
			{#each Array.from(uploadingBatches.values()) as batch}
				{#each Object.values(batch.tasks) as task}
					<tr class="border-b border-default hover:bg-surface-sunken/50 transition-colors">
						<td class="px-4 py-3 text-on-surface">{task.file_name}</td>
						<td class="px-4 py-3 text-muted">{getFileExtension(task.file_name)}</td>
						<td class="px-4 py-3 text-muted">-</td>
						<td class="px-4 py-3">
							{#if task.status === 'failed'}
								<span class="text-red-400">Failed: {task.error || 'Unknown error'}</span>
							{:else if task.status === 'completed'}
								<span class="text-green-400">Completed</span>
							{:else}
								<div class="flex flex-col gap-1">
									<span class="text-blue-400">
										{task.status === 'pending' ? 'Pending' : 'Processing'}
									</span>
									{#if task.total_chunks && task.total_chunks > 0}
										<div class="w-full bg-surface-sunken rounded-full h-2">
											<div
												class="bg-blue-500 h-2 rounded-full transition-all"
												style="width: {getProgressPercentage(task)}%"
											></div>
										</div>
										<span class="text-xs text-muted">
											{task.completed_chunks || 0} / {task.total_chunks} chunks
										</span>
									{/if}
								</div>
							{/if}
						</td>
						<td class="px-4 py-3 text-muted">-</td>
					</tr>
				{/each}
			{/each}

			<!-- Indexed documents -->
			{#each filteredAndSortedDocs() as doc}
				<tr class="border-b border-default hover:bg-surface-sunken/50 transition-colors">
					<td class="px-4 py-3 text-on-surface">{doc.file_name}</td>
					<td class="px-4 py-3 text-muted">{doc.file_type}</td>
					<td class="px-4 py-3 text-muted">{formatFileSize(doc.file_size)}</td>
					<td class="px-4 py-3">
						<span class="text-green-400">Indexed ({doc.node_count} chunks)</span>
					</td>
					<td class="px-4 py-3">
						<button
							onclick={() => openDeleteDialog(doc)}
							class="px-3 py-1 rounded transition text-sm bg-red-500/20 text-red-400 hover:bg-red-500/30"
						>
							Delete
						</button>
					</td>
				</tr>
			{/each}

			{#if filteredAndSortedDocs().length === 0 && uploadingBatches.size === 0}
				<tr>
					<td colspan="5" class="px-4 py-12">
						<div class="flex flex-col items-center justify-center space-y-4">
							{#if searchQuery}
								<Search class="w-12 h-12 text-muted opacity-50" />
								<p class="text-muted text-center">No documents match your search.</p>
								<p class="text-on-surface-subtle text-sm">Try a different search term</p>
							{:else}
								<FileText class="w-16 h-16 text-primary opacity-50" />
								<div class="text-center space-y-2">
									<p class="text-muted font-medium">No documents yet</p>
									<p class="text-on-surface-subtle text-sm">Upload files above to get started</p>
								</div>
								<div class="flex items-center gap-2 text-xs text-on-surface-subtle mt-2">
									<Upload class="w-4 h-4" />
									<span>Supported: PDF, DOCX, TXT, MD, PPTX, XLSX, HTML</span>
								</div>
							{/if}
						</div>
					</td>
				</tr>
			{/if}
		</tbody>
	</table>
</div>

<ConfirmDialog
	open={deleteDialogOpen}
	title="Delete Document"
	message={documentToDelete ? `Are you sure you want to delete "${documentToDelete.file_name}"? This action cannot be undone.` : ''}
	confirmText="Delete"
	cancelText="Cancel"
	onConfirm={confirmDelete}
	onCancel={cancelDelete}
/>
