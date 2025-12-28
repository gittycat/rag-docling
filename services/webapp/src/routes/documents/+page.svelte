<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import { onMount } from 'svelte';
	import { fetchDocuments, deleteDocument, type Document } from '$lib/api';

	let documents = $state<Document[]>([]);
	let selectedIds = new SvelteSet<string>();
	let isLoading = $state(true);
	let error = $state<string | null>(null);
	let isDeleting = $state(false);

	const allSelected = $derived(documents.length > 0 && selectedIds.size === documents.length);
	const someSelected = $derived(selectedIds.size > 0);

	onMount(async () => {
		await loadDocuments();
	});

	async function loadDocuments() {
		isLoading = true;
		error = null;
		try {
			documents = await fetchDocuments();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load documents';
		} finally {
			isLoading = false;
		}
	}

	function formatSize(bytes: number | undefined): string {
		if (bytes === undefined) return '—';
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function toggleSelectAll() {
		if (allSelected) {
			selectedIds.clear();
		} else {
			documents.forEach((d) => selectedIds.add(d.id));
		}
	}

	function toggleSelect(id: string) {
		if (selectedIds.has(id)) {
			selectedIds.delete(id);
		} else {
			selectedIds.add(id);
		}
	}

	async function handleDeleteDocument(id: string) {
		if (!confirm('Are you sure you want to delete this document?')) return;

		isDeleting = true;
		try {
			await deleteDocument(id);
			selectedIds.delete(id);
			await loadDocuments();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to delete document';
		} finally {
			isDeleting = false;
		}
	}

	async function handleDeleteSelected() {
		if (!confirm(`Are you sure you want to delete ${selectedIds.size} document(s)?`)) return;

		isDeleting = true;
		try {
			const idsToDelete = Array.from(selectedIds);
			for (const id of idsToDelete) {
				await deleteDocument(id);
			}
			selectedIds.clear();
			await loadDocuments();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to delete documents';
		} finally {
			isDeleting = false;
		}
	}
</script>

<div class="flex flex-col h-full gap-4">
	<!-- Action Bar -->
	<div class="flex items-center gap-2 bg-base-200 px-3 py-2 rounded-lg">
		<button
			class="btn btn-sm btn-square btn-action has-tooltip text-error"
			disabled={!someSelected || isDeleting}
			onclick={handleDeleteSelected}
			data-tooltip="Delete selected ({selectedIds.size})"
			aria-label="Delete selected documents"
		>
			{#if isDeleting}
				<span class="loading loading-spinner loading-xs"></span>
			{:else}
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
						d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
					/>
				</svg>
			{/if}
		</button>
		<button
			class="btn btn-sm btn-square btn-action has-tooltip"
			onclick={loadDocuments}
			disabled={isLoading}
			data-tooltip="Refresh"
			aria-label="Refresh document list"
		>
			{#if isLoading}
				<span class="loading loading-spinner loading-xs"></span>
			{:else}
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
			{/if}
		</button>
		<div class="flex-1"></div>
		<a
			href="/upload?trigger=files"
			class="btn btn-sm btn-square btn-action has-tooltip"
			data-tooltip="Upload files"
			aria-label="Upload files"
		>
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
					d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
				/>
			</svg>
		</a>
		<a
			href="/upload?trigger=directory"
			class="btn btn-sm btn-square btn-action has-tooltip"
			data-tooltip="Upload directory"
			aria-label="Upload directory"
		>
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
					d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
				/>
			</svg>
		</a>
	</div>

	<!-- Error Alert -->
	{#if error}
		<div class="alert alert-error">
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
			<button class="btn btn-ghost btn-sm" onclick={() => (error = null)}>Dismiss</button>
		</div>
	{/if}

	<!-- Documents Table -->
	<div class="overflow-x-auto flex-1">
		{#if isLoading && documents.length === 0}
			<div class="flex items-center justify-center h-full">
				<span class="loading loading-spinner loading-lg"></span>
			</div>
		{:else}
			<table class="table table-xs table-pin-rows">
				<thead>
					<tr class="bg-base-200">
						<th class="w-8">
							<label>
								<input
									type="checkbox"
									class="checkbox checkbox-xs"
									checked={allSelected}
									onchange={toggleSelectAll}
								/>
							</label>
						</th>
						<th>Name</th>
						<th class="w-24 text-right">Chunks</th>
						<th class="w-16"></th>
					</tr>
				</thead>
				<tbody>
					{#each documents as doc (doc.id)}
						<tr class="hover">
							<th>
								<label>
									<input
										type="checkbox"
										class="checkbox checkbox-xs"
										checked={selectedIds.has(doc.id)}
										onchange={() => toggleSelect(doc.id)}
									/>
								</label>
							</th>
							<td class="font-mono text-xs truncate max-w-md" title={doc.file_name}>
								{doc.file_name}
							</td>
							<td class="text-right text-xs">{doc.chunks}</td>
							<td>
								<button
									class="btn btn-ghost btn-xs text-error"
									onclick={() => handleDeleteDocument(doc.id)}
									title="Delete document"
									aria-label="Delete {doc.file_name}"
									disabled={isDeleting}
								>
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
											d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
										/>
									</svg>
								</button>
							</td>
						</tr>
					{:else}
						<tr>
							<td colspan="4" class="text-center py-8 text-base-content/50">
								No documents indexed yet.
								<a href="/upload" class="link link-primary">Upload documents</a> to get started.
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</div>
</div>
