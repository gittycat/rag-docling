<script lang="ts">
	import {
		uploadFiles,
		fetchBatchProgress,
		computeFileHash,
		checkDuplicateFiles,
		type BatchProgressResponse,
		type TaskStatus,
		type FileCheckItem
	} from '$lib/api';

	interface UploadItem {
		id: string;
		filename: string;
		size: number;
		uploadProgress: number;
		processingProgress: number;
		status: 'uploading' | 'processing' | 'done' | 'error' | 'skipped';
		error?: string;
		skipReason?: string;
		taskId?: string;
		batchId?: string;
	}

	let uploads = $state<UploadItem[]>([]);
	let fileInput: HTMLInputElement;
	let dirInput: HTMLInputElement;
	let isUploading = $state(false);

	// Active batches being polled
	let activeBatches = $state<Set<string>>(new Set());

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
			uploadProgress: 0,
			processingProgress: 0,
			status: 'uploading' as const
		}));

		uploads = [...newItems, ...uploads];

		try {
			// Step 1: Compute hashes for all files
			const fileChecks: FileCheckItem[] = [];
			const fileMap = new Map<string, File>();

			for (let i = 0; i < files.length; i++) {
				const file = files[i];
				const filename = file.webkitRelativePath || file.name;

				// Show progress for hashing
				uploads = uploads.map((item) => {
					if (item.id === newItems[i].id) {
						return { ...item, uploadProgress: 10 };
					}
					return item;
				});

				const hash = await computeFileHash(file);
				fileChecks.push({ filename, size: file.size, hash });
				fileMap.set(filename, file);

				// Update progress after hashing
				uploads = uploads.map((item) => {
					if (item.id === newItems[i].id) {
						return { ...item, uploadProgress: 30 };
					}
					return item;
				});
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
						if (newItems.some((n) => n.id === item.id && n.filename === filename)) {
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

			// Simulate upload progress for files being uploaded
			const uploadProgressInterval = setInterval(() => {
				uploads = uploads.map((item) => {
					if (
						newItems.some((n) => n.id === item.id) &&
						item.status === 'uploading' &&
						!skippedFiles.has(item.filename)
					) {
						const newProgress = Math.min(item.uploadProgress + 20, 90);
						return { ...item, uploadProgress: newProgress };
					}
					return item;
				});
			}, 100);

			const response = await uploadFiles(filesToUpload);

			clearInterval(uploadProgressInterval);

			// Mark upload as complete, update with task IDs, start processing
			uploads = uploads.map((item) => {
				const matchingTask = response.tasks.find(
					(t) => t.filename === item.filename || item.filename.endsWith(t.filename)
				);
				if (newItems.some((n) => n.id === item.id) && matchingTask) {
					return {
						...item,
						uploadProgress: 100,
						status: 'processing' as const,
						taskId: matchingTask.task_id,
						batchId: response.batch_id
					};
				} else if (newItems.some((n) => n.id === item.id) && !skippedFiles.has(item.filename)) {
					return { ...item, uploadProgress: 100, status: 'processing' as const };
				}
				return item;
			});

			// Start polling for this batch
			activeBatches.add(response.batch_id);
			pollBatchProgress(response.batch_id);
		} catch (error) {
			// Mark all non-skipped items as error
			uploads = uploads.map((item) => {
				if (newItems.some((n) => n.id === item.id) && item.status !== 'skipped') {
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
			} else if (taskStatus.status === 'processing') {
				// Indeterminate progress
				return { ...item, processingProgress: Math.min(item.processingProgress + 5, 90) };
			}
			return item;
		});
	}

	function clearCompleted() {
		uploads = uploads.filter((u) => u.status !== 'done' && u.status !== 'error' && u.status !== 'skipped');
	}

	function getStatusBadgeClass(status: UploadItem['status']): string {
		switch (status) {
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
	<!-- Upload Section -->
	<div class="flex gap-2 items-center">
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
		<button
			class="btn btn-primary btn-sm"
			onclick={() => fileInput.click()}
			disabled={isUploading}
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
			Upload Files
		</button>
		<button
			class="btn btn-secondary btn-sm"
			onclick={() => dirInput.click()}
			disabled={isUploading}
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
			Upload Directory
		</button>

		<div class="flex-1"></div>

		{#if uploads.some((u) => u.status === 'done' || u.status === 'error' || u.status === 'skipped')}
			<button class="btn btn-ghost btn-sm" onclick={clearCompleted}>Clear Completed</button>
		{/if}
		<span class="text-sm text-base-content/60">{uploads.length} uploads</span>
	</div>

	<!-- Supported formats info -->
	<div class="text-xs text-base-content/50">
		Supported formats: PDF, DOCX, PPTX, XLSX, HTML, TXT, MD, AsciiDoc
	</div>

	<!-- Upload Progress Table -->
	<div class="overflow-x-auto flex-1">
		<table class="table table-xs table-pin-rows">
			<thead>
				<tr class="bg-base-200">
					<th>Document</th>
					<th class="w-24 text-right">Size</th>
					<th class="w-40">Upload</th>
					<th class="w-40">Processing</th>
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
							<div class="flex items-center gap-2">
								<progress
									class="progress progress-info w-24"
									value={upload.uploadProgress}
									max="100"
								></progress>
								<span class="text-xs text-base-content/60">{upload.uploadProgress}%</span>
							</div>
						</td>
						<td>
							{#if upload.status === 'uploading'}
								<span class="text-xs text-base-content/40">Waiting...</span>
							{:else if upload.status === 'skipped'}
								<span class="text-xs text-base-content/40">—</span>
							{:else if upload.status === 'error' && upload.uploadProgress < 100}
								<span class="text-xs text-error">—</span>
							{:else}
								<div class="flex items-center gap-2">
									<progress
										class="progress progress-warning w-24"
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
									<span class="badge badge-sm {getStatusBadgeClass(upload.status)} cursor-help">
										Error
									</span>
								</div>
							{:else if upload.status === 'skipped' && upload.skipReason}
								<div class="tooltip tooltip-info tooltip-top z-50 before:-translate-y-1" data-tip={upload.skipReason}>
									<span class="badge badge-sm {getStatusBadgeClass(upload.status)} cursor-help">
										Skipped
									</span>
								</div>
							{:else}
								<span class="badge badge-sm {getStatusBadgeClass(upload.status)}">
									{upload.status === 'done'
										? 'Done'
										: upload.status === 'error'
											? 'Error'
											: upload.status === 'uploading'
												? 'Uploading'
												: upload.status === 'skipped'
													? 'Skipped'
													: 'Processing'}
								</span>
							{/if}
						</td>
					</tr>
				{:else}
					<tr>
						<td colspan="5" class="text-center py-8 text-base-content/50">
							No uploads in progress. Use the buttons above to upload documents.
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>
