<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onMount, tick } from 'svelte';
	import {
		uploadFiles,
		fetchBatchProgress,
		fetchAppConfig,
		computeFileHash,
		checkDuplicateFiles,
		type BatchProgressResponse,
		type FileCheckItem
	} from '$lib/api';

	interface UploadItem {
		id: string;
		filename: string;
		size: number;
		/**
		 * Fraction of chunks indexed, 0–100. Null means the server has not reported
		 * a chunk count yet — the bar stays indeterminate rather than inventing one.
		 */
		processingProgress: number | null;
		status: 'hashing' | 'uploading' | 'processing' | 'done' | 'error' | 'skipped';
		error?: string;
		skipReason?: string;
		taskId?: string;
		batchId?: string;
	}

	// Phases before the server reports chunk counts have no measurable progress.
	function isIndeterminate(item: UploadItem): boolean {
		return (
			item.status === 'hashing' ||
			item.status === 'uploading' ||
			(item.status === 'processing' && item.processingProgress === null)
		);
	}

	const PHASE_LABEL: Record<UploadItem['status'], string> = {
		hashing: 'Hashing',
		uploading: 'Uploading',
		processing: 'Processing',
		done: 'Done',
		error: 'Error',
		skipped: 'Skipped'
	};

	let uploads = $state<UploadItem[]>([]);
	let fileInput: HTMLInputElement;
	let dirInput: HTMLInputElement;
	let isUploading = $state(false);
	let ollamaError = $state<string | null>(null);
	let maxUploadSizeMb = $state<number | null>(null);

	// Active batches being polled
	let activeBatches = $state<Set<string>>(new Set());

	// Auto-trigger file picker based on query parameter
	onMount(async () => {
		// Advisory limit from the server, so oversized files fail before the upload.
		fetchAppConfig()
			.then((cfg) => (maxUploadSizeMb = cfg.max_upload_size_mb))
			.catch(() => (maxUploadSizeMb = null));

		await tick();
		const trigger = $page.url.searchParams.get('trigger');

		// Set up cancel handlers to redirect back to Documents if user cancels picker
		const handleCancel = () => {
			// Only redirect if no uploads are in progress
			if (uploads.length === 0) {
				goto('/documents');
			}
		};

		if (trigger === 'files' && fileInput) {
			fileInput.addEventListener('cancel', handleCancel);
			fileInput.click();
		} else if (trigger === 'directory' && dirInput) {
			dirInput.addEventListener('cancel', handleCancel);
			dirInput.click();
		}
	});

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	async function handleFileUpload(event: Event) {
		const input = event.target as HTMLInputElement;
		if (!input.files || input.files.length === 0) return;
		await processUpload(Array.from(input.files));
		input.value = '';
	}

	async function handleDirUpload(event: Event) {
		const input = event.target as HTMLInputElement;
		if (!input.files || input.files.length === 0) return;
		await processUpload(Array.from(input.files));
		input.value = '';
	}

	async function processUpload(files: File[]) {
		isUploading = true;

		// Create upload items for UI
		const newItems: UploadItem[] = files.map((file, idx) => ({
			id: `upload-${Date.now()}-${idx}`,
			filename: file.webkitRelativePath || file.name,
			size: file.size,
			processingProgress: null,
			status: 'hashing' as const
		}));

		uploads = [...newItems, ...uploads];

		// Reject files above the server's limit before spending time hashing them.
		const limitBytes = maxUploadSizeMb != null ? maxUploadSizeMb * 1024 * 1024 : null;
		const oversized = new Set<string>();
		if (limitBytes != null) {
			for (const item of newItems) {
				if (item.size > limitBytes) oversized.add(item.id);
			}
			if (oversized.size > 0) {
				uploads = uploads.map((item) =>
					oversized.has(item.id)
						? {
								...item,
								status: 'error' as const,
								error: `File is ${formatSize(item.size)} — over the ${maxUploadSizeMb} MB upload limit`
							}
						: item
				);
			}
		}

		const acceptedItems = newItems.filter((n) => !oversized.has(n.id));
		const acceptedFiles = files.filter((_, idx) => !oversized.has(newItems[idx].id));
		if (acceptedFiles.length === 0) {
			isUploading = false;
			return;
		}

		try {
			// Step 1: Compute hashes for all files
			const fileChecks: FileCheckItem[] = [];
			const fileMap = new Map<string, File>();

			for (let i = 0; i < acceptedFiles.length; i++) {
				const file = acceptedFiles[i];
				const filename = file.webkitRelativePath || file.name;

				const hash = await computeFileHash(file);
				fileChecks.push({ filename, size: file.size, hash });
				fileMap.set(filename, file);

				uploads = uploads.map((item) =>
					item.id === acceptedItems[i].id ? { ...item, status: 'uploading' as const } : item
				);
			}

			// Step 2: Check for duplicates
			const duplicateCheck = await checkDuplicateFiles(fileChecks);

			// Step 3: Separate files into upload vs skipped
			const filesToUpload: File[] = [];
			const skippedFiles = new Set<string>();

			for (const filename of fileMap.keys()) {
				const checkResult = duplicateCheck.results[filename];
				if (checkResult?.exists) {
					skippedFiles.add(filename);
					// Mark as skipped immediately
					uploads = uploads.map((item) => {
						if (acceptedItems.some((n) => n.id === item.id && n.filename === filename)) {
							return {
								...item,
								status: 'skipped' as const,
								skipReason: checkResult.reason || 'Already uploaded'
							};
						}
						return item;
					});
				} else {
					filesToUpload.push(fileMap.get(filename)!);
				}
			}

			// Step 4: Upload non-duplicate files only
			if (filesToUpload.length === 0) {
				// All files were duplicates
				isUploading = false;
				return;
			}

			// No byte-level upload progress is available from fetch(), so the bar stays
			// indeterminate until the server hands back task IDs and real chunk counts.
			const response = await uploadFiles(filesToUpload);

			// Mark upload as complete, update with task IDs, start processing
			// Track matched tasks to avoid duplicate assignments
			const matchedTaskIds = new Set<string>();

			uploads = uploads.map((item) => {
				if (!acceptedItems.some((n) => n.id === item.id)) {
					return item;
				}

				if (skippedFiles.has(item.filename)) {
					return item;
				}

				// Try exact match first, then fallback to suffix match
				const matchingTask = response.tasks.find(
					(t) => !matchedTaskIds.has(t.task_id) && (
						t.filename === item.filename || item.filename.endsWith(t.filename)
					)
				);

				if (matchingTask) {
					matchedTaskIds.add(matchingTask.task_id);
					return {
						...item,
						status: 'processing' as const,
						taskId: matchingTask.task_id,
						batchId: response.batch_id
					};
				} else {
					// No matching task found - this shouldn't happen but handle gracefully
					console.warn(`No matching task found for file: ${item.filename}`);
					return {
						...item,
						status: 'error' as const,
						error: 'Failed to match upload task'
					};
				}
			});

			// Start polling for this batch
			activeBatches.add(response.batch_id);
			pollBatchProgress(response.batch_id);
		} catch (error) {
			// Show prominent alert for Ollama connectivity issues
			if (error instanceof Error && error.name === 'ServiceUnavailable') {
				ollamaError = error.message;
			}

			// Mark all non-skipped items as error
			uploads = uploads.map((item) => {
				if (acceptedItems.some((n) => n.id === item.id) && item.status !== 'skipped') {
					return {
						...item,
						status: 'error' as const,
						error: error instanceof Error ? error.message : 'Upload failed'
					};
				}
				return item;
			});
		} finally {
			isUploading = false;
		}
	}

	async function pollBatchProgress(batchId: string) {
		const pollInterval = setInterval(async () => {
			try {
				const progress = await fetchBatchProgress(batchId);
				updateProcessingProgress(progress);

				// Check if all tasks are complete
				const allDone = Object.values(progress.tasks).every(
					(t) => t.status === 'completed' || t.status === 'error'
				);

				if (allDone) {
					clearInterval(pollInterval);
					activeBatches.delete(batchId);
				}
			} catch {
				// Batch might have expired or error occurred
				clearInterval(pollInterval);
				activeBatches.delete(batchId);
			}
		}, 1000);
	}

	function updateProcessingProgress(progress: BatchProgressResponse) {
		uploads = uploads.map((item) => {
			if (item.batchId !== progress.batch_id) return item;

			const taskStatus = item.taskId ? progress.tasks[item.taskId] : null;
			if (!taskStatus) return item;

			if (taskStatus.status === 'completed') {
				return { ...item, processingProgress: 100, status: 'done' as const };
			} else if (taskStatus.status === 'error') {
				return {
					...item,
					status: 'error' as const,
					error: taskStatus.data?.error || 'Processing failed'
				};
			} else if (taskStatus.total_chunks && taskStatus.completed_chunks !== undefined) {
				const pct = Math.round((taskStatus.completed_chunks / taskStatus.total_chunks) * 100);
				return { ...item, processingProgress: pct };
			}
			// Server has no chunk counts yet — leave the bar indeterminate rather
			// than inventing progress for a task that may be stalled.
			return item;
		});
	}

	function clearCompleted() {
		uploads = uploads.filter((u) => u.status !== 'done' && u.status !== 'error' && u.status !== 'skipped');
	}

	function getStatusBadgeClass(status: UploadItem['status']): string {
		switch (status) {
			case 'hashing':
			case 'uploading':
				return 'badge-info';
			case 'processing':
				return 'badge-warning';
			case 'done':
				return 'badge-success';
			case 'error':
				return 'badge-error';
			case 'skipped':
				return 'badge-ghost';
			default:
				return 'badge-ghost';
		}
	}
</script>

<div class="flex flex-col h-full gap-4">
	{#if ollamaError}
		<div role="alert" class="alert alert-error shadow-lg">
			<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 shrink-0 stroke-current" fill="none" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
			</svg>
			<div>
				<h3 class="font-bold">Ollama is not accessible</h3>
				<p class="text-sm">Ollama is required for generating embeddings. Check that it is running and reachable, then try uploading again.</p>
			</div>
			<button class="btn btn-sm btn-ghost" onclick={() => ollamaError = null}>Dismiss</button>
		</div>
	{/if}

	<!-- Hidden file inputs (triggered from Documents page) -->
	<input
		bind:this={fileInput}
		type="file"
		multiple
		class="hidden"
		onchange={handleFileUpload}
		accept=".txt,.md,.pdf,.docx,.pptx,.xlsx,.html,.htm,.asciidoc,.adoc"
	/>
	<input
		bind:this={dirInput}
		type="file"
		webkitdirectory
		class="hidden"
		onchange={handleDirUpload}
	/>

	<!-- Action Bar -->
	<div class="flex gap-2 items-center">
		{#if uploads.some((u) => u.status === 'done' || u.status === 'error' || u.status === 'skipped')}
			<button class="btn btn-ghost btn-sm" onclick={clearCompleted}>Clear Completed</button>
		{/if}
		<div class="flex-1"></div>
		<span class="text-sm text-base-content/60">{uploads.length} uploads</span>
	</div>

	<!-- Supported formats info -->
	<div class="text-xs text-base-content/50">
		Supported formats: PDF, DOCX, PPTX, XLSX, HTML, TXT, MD, AsciiDoc
		{#if maxUploadSizeMb != null}
			· max {maxUploadSizeMb} MB per file
		{/if}
	</div>

	<!-- Upload Progress Table -->
	<div class="overflow-x-auto flex-1">
		<table class="table table-xs table-pin-rows">
			<thead>
				<tr class="bg-base-200">
					<th>Document</th>
					<th class="w-24 text-right">Size</th>
					<th class="w-48">Progress</th>
					<th class="w-24">Status</th>
				</tr>
			</thead>
			<tbody>
				{#each uploads as upload (upload.id)}
					<tr class="hover">
						<td class="font-mono text-xs truncate max-w-md" title={upload.filename}>
							{upload.filename}
						</td>
						<td class="text-right text-xs">{formatSize(upload.size)}</td>
						<td>
							{#if upload.status === 'skipped'}
								<span class="text-xs text-base-content/40">—</span>
							{:else if upload.status === 'error'}
								<span class="text-xs text-error">Failed</span>
							{:else if upload.status === 'done'}
								<div class="flex items-center gap-2">
									<progress class="progress progress-success w-32" value="100" max="100"></progress>
									<span class="text-xs text-base-content/60">100%</span>
								</div>
							{:else if isIndeterminate(upload)}
								<!-- No real progress signal yet: never fake a percentage. -->
								<div class="flex items-center gap-2">
									<progress class="progress progress-info w-32"></progress>
									<span class="text-xs text-base-content/60">{PHASE_LABEL[upload.status]}…</span>
								</div>
							{:else}
								<div class="flex items-center gap-2">
									<progress
										class="progress progress-warning w-32"
										value={upload.processingProgress}
										max="100"
									></progress>
									<span class="text-xs text-base-content/60">{upload.processingProgress}%</span>
								</div>
							{/if}
						</td>
						<td class="relative">
							{#if upload.status === 'error' && upload.error}
								<div class="tooltip tooltip-error tooltip-top z-50 before:-translate-y-1" data-tip={upload.error}>
									<span class="badge badge-sm {getStatusBadgeClass(upload.status)}">
										Error
									</span>
								</div>
							{:else if upload.status === 'skipped' && upload.skipReason}
								<div class="tooltip tooltip-info tooltip-top z-50 before:-translate-y-1" data-tip={upload.skipReason}>
									<span class="badge badge-sm {getStatusBadgeClass(upload.status)}">
										Skipped
									</span>
								</div>
							{:else}
								<span class="badge badge-sm {getStatusBadgeClass(upload.status)}">
									{PHASE_LABEL[upload.status]}
								</span>
							{/if}
						</td>
					</tr>
				{:else}
					<tr>
						<td colspan="4" class="text-center py-8 text-base-content/50">
							No uploads in progress. Use the buttons above to upload documents.
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>
