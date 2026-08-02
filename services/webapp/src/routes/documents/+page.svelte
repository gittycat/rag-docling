<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import { onMount } from 'svelte';
	import {
		fetchDocuments,
		deleteDocument,
		type Document,
		type DocumentSortField,
		type SortOrder
	} from '$lib/api';

	let documents = $state<Document[]>([]);
	let selectedIds = new SvelteSet<string>();
	let isLoading = $state(true);
	let error = $state<string | null>(null);
	let deleteFailures = $state<{ id: string; name: string; reason: string }[]>([]);
	let isDeleting = $state(false);

	// Sorting state
	let sortBy = $state<DocumentSortField>('uploaded_at');
	let sortOrder = $state<SortOrder>('desc');

	// Pagination over the fetched list (the API returns everything in one call).
	const PAGE_SIZES = [15, 25, 50, 100];
	let pageSize = $state(25);
	let page = $state(1);

	const allSelected = $derived(documents.length > 0 && selectedIds.size === documents.length);
	const someSelected = $derived(selectedIds.size > 0);

	const pageCount = $derived(Math.max(1, Math.ceil(documents.length / pageSize)));
	// Clamp when the list shrinks (deletes, sort changes) so the page is never empty.
	const currentPage = $derived(Math.min(page, pageCount));
	const pageStart = $derived((currentPage - 1) * pageSize);
	const visibleDocuments = $derived(documents.slice(pageStart, pageStart + pageSize));

	function goToPage(next: number) {
		page = Math.min(Math.max(1, next), pageCount);
	}

	onMount(async () => {
		await loadDocuments();
	});

	async function loadDocuments() {
		isLoading = true;
		error = null;
		try {
			documents = await fetchDocuments(sortBy, sortOrder);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load documents';
		} finally {
			isLoading = false;
		}
	}

	function formatUploadTime(isoString: string | undefined): string {
		if (!isoString) return '—';
		try {
			const date = new Date(isoString);
			const seconds = Math.floor((Date.now() - date.getTime()) / 1000);

			if (seconds < 60) return 'just now';

			const minutes = Math.floor(seconds / 60);
			if (minutes < 60) return `${minutes} min ago`;

			const hours = Math.floor(minutes / 60);
			if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;

			const days = Math.floor(hours / 24);
			if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`;

			return date.toISOString().split('T')[0]; // YYYY-MM-DD
		} catch {
			return '—';
		}
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
		deleteFailures = [];
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
		error = null;
		deleteFailures = [];
		try {
			const idsToDelete = Array.from(selectedIds);
			const nameOf = new Map(documents.map((d) => [d.id, d.file_name]));

			// A partial failure must not be reported as success: settle every delete,
			// keep the ones that failed selected, and name them.
			const results = await Promise.allSettled(idsToDelete.map((id) => deleteDocument(id)));

			const failures: { id: string; name: string; reason: string }[] = [];
			results.forEach((result, i) => {
				const id = idsToDelete[i];
				if (result.status === 'fulfilled') {
					selectedIds.delete(id);
				} else {
					failures.push({
						id,
						name: nameOf.get(id) ?? id,
						reason:
							result.reason instanceof Error ? result.reason.message : 'Delete failed'
					});
				}
			});

			deleteFailures = failures;
			if (failures.length > 0) {
				const succeeded = idsToDelete.length - failures.length;
				error = `${succeeded} of ${idsToDelete.length} document(s) deleted — ${failures.length} failed.`;
			}

			await loadDocuments();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to delete documents';
		} finally {
			isDeleting = false;
		}
	}

	async function handleSort(field: DocumentSortField) {
		if (sortBy === field) {
			// Toggle order if same field
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			// New field, default to desc for uploaded_at and chunks, asc for name
			sortBy = field;
			sortOrder = field === 'name' ? 'asc' : 'desc';
		}
		page = 1;
		await loadDocuments();
	}

	function getSortIcon(field: DocumentSortField): string {
		if (sortBy !== field) return '⇅';
		return sortOrder === 'asc' ? '↑' : '↓';
	}
</script>

<div class="flex flex-col h-full gap-4">
	<!-- Action Bar -->
	<div class="flex items-center gap-2 bg-base-200 px-3 py-2 rounded-lg">
		<div class="tooltip tooltip-bottom" data-tip="Delete selected ({selectedIds.size})">
			<button
				class="btn btn-sm btn-square btn-action text-error disabled:text-base-content/30"
				disabled={!someSelected || isDeleting}
				onclick={handleDeleteSelected}
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
		</div>
		<div class="tooltip tooltip-bottom" data-tip="Refresh">
			<button
				class="btn btn-sm btn-square btn-action"
				onclick={loadDocuments}
				disabled={isLoading}
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
		</div>
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
			<div class="flex-1">
				<div>{error}</div>
				{#if deleteFailures.length > 0}
					<ul class="mt-1 text-xs font-mono list-disc list-inside">
						{#each deleteFailures as failure (failure.id)}
							<li class="truncate" title="{failure.name}: {failure.reason}">
								{failure.name} — {failure.reason}
							</li>
						{/each}
					</ul>
				{/if}
			</div>
			<button
				class="btn btn-ghost btn-sm"
				onclick={() => {
					error = null;
					deleteFailures = [];
				}}>Dismiss</button
			>
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
							<label title="Select all {documents.length} documents (every page)">
								<input
									type="checkbox"
									class="checkbox checkbox-xs"
									checked={allSelected}
									onchange={toggleSelectAll}
									aria-label="Select all documents"
								/>
							</label>
						</th>
						<th>
							<button
								class="flex items-center gap-1 hover:text-primary transition-colors"
								onclick={() => handleSort('name')}
								title="Sort by name"
							>
								Name
								<span class="text-xs opacity-60">{getSortIcon('name')}</span>
							</button>
						</th>
						<th class="w-24">
							<div class="tooltip tooltip-bottom" data-tip="Text segments created for search indexing">
								<button
									class="flex items-center gap-1 w-full justify-end hover:text-primary transition-colors"
									onclick={() => handleSort('chunks')}
								>
									Chunks
									<span class="text-xs opacity-60">{getSortIcon('chunks')}</span>
								</button>
							</div>
						</th>
						<th class="w-44">
							<button
								class="flex items-center gap-1 w-full justify-end hover:text-primary transition-colors"
								onclick={() => handleSort('uploaded_at')}
								title="Sort by upload time"
							>
								Added
								<span class="text-xs opacity-60">{getSortIcon('uploaded_at')}</span>
							</button>
						</th>
						<th class="w-16"></th>
					</tr>
				</thead>
				<tbody>
					{#each visibleDocuments as doc (doc.id)}
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
							<td class="text-right text-xs font-mono text-base-content/70">
								{formatUploadTime(doc.uploaded_at)}
							</td>
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
							<td colspan="5" class="text-center py-8 text-base-content/50">
								No documents indexed yet.
								<a href="/upload" class="link link-primary">Upload documents</a> to get started.
							</td>
						</tr>
					{/each}
				</tbody>
			</table>

			<!-- Pagination -->
			{#if documents.length > 0}
				<div
					class="flex items-center gap-3 flex-wrap py-2 px-2 text-xs text-base-content/60 bg-base-200/50 border-t border-base-300"
				>
					<span class="font-mono tabular-nums">
						{pageStart + 1}–{Math.min(pageStart + pageSize, documents.length)} of {documents.length}
					</span>
					<label class="flex items-center gap-1">
						<span>Rows</span>
						<select
							class="select select-xs select-bordered"
							bind:value={pageSize}
							onchange={() => (page = 1)}
						>
							{#each PAGE_SIZES as size}
								<option value={size}>{size}</option>
							{/each}
						</select>
					</label>
					<div class="flex-1"></div>
					<div class="join">
						<button
							class="btn btn-xs join-item"
							onclick={() => goToPage(currentPage - 1)}
							disabled={currentPage <= 1}
							aria-label="Previous page">‹</button
						>
						<span class="btn btn-xs join-item pointer-events-none font-mono">
							{currentPage} / {pageCount}
						</span>
						<button
							class="btn btn-xs join-item"
							onclick={() => goToPage(currentPage + 1)}
							disabled={currentPage >= pageCount}
							aria-label="Next page">›</button
						>
					</div>
				</div>
			{/if}
		{/if}
	</div>
</div>
