<script lang="ts">
	import { uploadFiles, getConfig } from '$lib/utils/api';
	import { toast } from '$lib/stores/toast.svelte';
	import { onMount } from 'svelte';
	import { Upload, FolderOpen } from 'lucide-svelte';

	let fileInput: HTMLInputElement;
	let folderInput: HTMLInputElement;
	let maxUploadSizeMb = $state(80);
	let isUploading = $state(false);

	interface Props {
		onUploadStart: (batchId: string) => void;
	}

	let { onUploadStart }: Props = $props();

	onMount(async () => {
		try {
			const config = await getConfig();
			maxUploadSizeMb = config.max_upload_size_mb;
		} catch (error) {
			console.error('Failed to load config:', error);
			toast.error('Failed to load upload configuration');
		}
	});

	async function handleFilesSelected(files: FileList | null) {
		if (!files || files.length === 0) return;

		const fileArray = Array.from(files);
		const totalSize = fileArray.reduce((sum, file) => sum + file.size, 0);
		const totalSizeMb = totalSize / (1024 * 1024);

		if (totalSizeMb > maxUploadSizeMb) {
			toast.error(`Total file size (${totalSizeMb.toFixed(2)} MB) exceeds limit of ${maxUploadSizeMb} MB`);
			return;
		}

		isUploading = true;
		const fileCount = fileArray.length;
		const fileWord = fileCount === 1 ? 'file' : 'files';
		toast.info(`Uploading ${fileCount} ${fileWord}...`);

		try {
			const batchId = await uploadFiles(fileArray);
			onUploadStart(batchId);
			toast.success(`Started processing ${fileCount} ${fileWord}`);
		} catch (error) {
			const message = error instanceof Error ? error.message : 'Upload failed';
			toast.error(message);
		} finally {
			isUploading = false;
			if (fileInput) fileInput.value = '';
			if (folderInput) folderInput.value = '';
		}
	}

	function handleAddFiles() {
		fileInput.click();
	}

	function handleAddFolder() {
		folderInput.click();
	}
</script>

<div class="flex flex-col gap-2">
	<div class="flex gap-4 items-center">
		<input
			bind:this={fileInput}
			type="file"
			multiple
			class="hidden"
			onchange={(e) => handleFilesSelected(e.currentTarget.files)}
			accept=".txt,.md,.pdf,.docx,.pptx,.xlsx,.html,.htm,.asciidoc,.adoc"
		/>
		<input
			bind:this={folderInput}
			type="file"
			webkitdirectory
			class="hidden"
			onchange={(e) => handleFilesSelected(e.currentTarget.files)}
		/>

		<button
			onclick={handleAddFiles}
			disabled={isUploading}
			class="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover
						 disabled:opacity-50 disabled:cursor-not-allowed transition"
		>
			<Upload class="w-4 h-4" />
			Add Files
		</button>

		<button
			onclick={handleAddFolder}
			disabled={isUploading}
			class="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700
						 disabled:opacity-50 disabled:cursor-not-allowed transition"
		>
			<FolderOpen class="w-4 h-4" />
			Add Folder
		</button>

		{#if isUploading}
			<span class="text-muted">Uploading...</span>
		{/if}
	</div>

	<div class="text-sm text-muted">
		Max upload size: {maxUploadSizeMb} MB
	</div>
</div>
