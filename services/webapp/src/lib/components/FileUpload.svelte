<script lang="ts">
	import { uploadFiles, getConfig } from '$lib/utils/api';
	import { documentsStore } from '$lib/stores/documents';
	import { onMount } from 'svelte';

	let fileInput: HTMLInputElement;
	let folderInput: HTMLInputElement;
	let maxUploadSizeMb = $state(80);
	let isUploading = $state(false);
	let uploadError = $state<string | null>(null);

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
		}
	});

	async function handleFilesSelected(files: FileList | null) {
		if (!files || files.length === 0) return;

		uploadError = null;

		const fileArray = Array.from(files);
		const totalSize = fileArray.reduce((sum, file) => sum + file.size, 0);
		const totalSizeMb = totalSize / (1024 * 1024);

		if (totalSizeMb > maxUploadSizeMb) {
			uploadError = `Total file size (${totalSizeMb.toFixed(2)} MB) exceeds limit of ${maxUploadSizeMb} MB`;
			return;
		}

		isUploading = true;

		try {
			const batchId = await uploadFiles(fileArray);
			onUploadStart(batchId);
		} catch (error) {
			uploadError = error instanceof Error ? error.message : 'Upload failed';
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
		class="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition"
	>
		Add Files
	</button>

	<button
		onclick={handleAddFolder}
		disabled={isUploading}
		class="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition"
	>
		Add Folder
	</button>

	{#if isUploading}
		<span class="text-gray-600">Uploading...</span>
	{/if}
</div>

{#if uploadError}
	<div class="mt-2 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
		{uploadError}
	</div>
{/if}

<div class="mt-2 text-sm text-gray-600">
	Max upload size: {maxUploadSizeMb} MB
</div>
