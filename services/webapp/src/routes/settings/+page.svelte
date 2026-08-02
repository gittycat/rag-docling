<script lang="ts">
	import { onMount } from 'svelte';
	import { showTooltips } from '$lib/stores/ui';
	import {
		fetchApiKeyStatus,
		setApiKey,
		fetchSettings,
		updateSettings,
		type ApiKeyStatus
	} from '$lib/api';

	let apiKeyStatuses: ApiKeyStatus[] = [];
	let loading = true;
	let apiKeyInputs: Record<string, string> = {};
	let validatingProvider: string | null = null;
	let validationErrors: Record<string, string> = {};
	let validationSuccess: Record<string, boolean> = {};

	let contextualRetrievalEnabled = true;
	let settingsLoading = true;

	// A settings screen that fails silently makes users believe they changed
	// something they did not — every failure gets a visible state.
	let apiKeysLoadError: string | null = null;
	let settingsLoadError: string | null = null;
	let settingsUpdateError: string | null = null;

	onMount(load);

	async function load() {
		loading = true;
		settingsLoading = true;
		apiKeysLoadError = null;
		settingsLoadError = null;

		const [keyResult, settingsResult] = await Promise.allSettled([
			fetchApiKeyStatus(),
			fetchSettings()
		]);

		if (keyResult.status === 'fulfilled') {
			apiKeyStatuses = keyResult.value;
			apiKeyStatuses.forEach((status) => {
				apiKeyInputs[status.provider] = status.masked_key || '';
			});
		} else {
			apiKeyStatuses = [];
			apiKeysLoadError = errorMessage(keyResult.reason, 'Failed to load API key status');
		}

		if (settingsResult.status === 'fulfilled') {
			contextualRetrievalEnabled = settingsResult.value.contextual_retrieval_enabled;
		} else {
			settingsLoadError = errorMessage(settingsResult.reason, 'Failed to load settings');
		}

		loading = false;
		settingsLoading = false;
	}

	function errorMessage(err: unknown, fallback: string): string {
		return err instanceof Error ? err.message : fallback;
	}

	async function handleContextualRetrievalToggle() {
		settingsUpdateError = null;
		try {
			const result = await updateSettings({
				contextual_retrieval_enabled: contextualRetrievalEnabled
			});
			contextualRetrievalEnabled = result.contextual_retrieval_enabled;
		} catch (error) {
			// Revert on failure so the checkbox reflects the server, not the click
			contextualRetrievalEnabled = !contextualRetrievalEnabled;
			settingsUpdateError = errorMessage(error, 'Failed to update setting');
		}
	}

	async function handleApiKeySubmit(provider: string) {
		const apiKey = apiKeyInputs[provider];
		if (!apiKey || apiKey.trim() === '') {
			return;
		}

		// Don't submit if it's still the masked value
		if (apiKey.includes('***')) {
			return;
		}

		validatingProvider = provider;
		delete validationErrors[provider];
		delete validationSuccess[provider];

		try {
			const result = await setApiKey(provider, apiKey);
			validationSuccess[provider] = true;
			apiKeyInputs[provider] = result.masked_key;

			// Update the status list
			const statusIndex = apiKeyStatuses.findIndex((s) => s.provider === provider);
			if (statusIndex >= 0) {
				apiKeyStatuses[statusIndex] = {
					provider,
					has_key: true,
					masked_key: result.masked_key
				};
			}

			// Clear success indicator after 3 seconds
			setTimeout(() => {
				delete validationSuccess[provider];
				validationSuccess = { ...validationSuccess };
			}, 3000);
		} catch (error) {
			validationErrors[provider] = error instanceof Error ? error.message : 'Validation failed';
		} finally {
			validatingProvider = null;
		}
	}

	function handleKeyDown(event: KeyboardEvent, provider: string) {
		if (event.key === 'Enter') {
			handleApiKeySubmit(provider);
		}
	}

	function handleInput(provider: string) {
		// Clear error when user starts typing
		delete validationErrors[provider];
		delete validationSuccess[provider];
		validationErrors = { ...validationErrors };
		validationSuccess = { ...validationSuccess };
	}
</script>

<div class="flex flex-col gap-2">
	<!-- User Interface Section -->
	<div class="bg-base-200 rounded p-2">
		<div class="text-xs font-semibold mb-1 text-base-content/70">User Interface</div>
		<label class="flex items-center gap-2 text-xs cursor-pointer">
			<input
				type="checkbox"
				class="checkbox checkbox-xs rounded-none"
				bind:checked={$showTooltips}
			/>
			<span>Show help tooltips</span>
		</label>
	</div>

	<!-- RAG Pipeline Section -->
	<div class="bg-base-200 rounded p-2">
		<div class="text-xs font-semibold mb-1 text-base-content/70">RAG Pipeline</div>
		{#if settingsLoading}
			<div class="text-xs text-base-content/60">Loading...</div>
		{:else if settingsLoadError}
			<div class="alert alert-error text-xs py-1 px-2 flex items-center gap-2">
				<span class="flex-1">Could not load pipeline settings: {settingsLoadError}</span>
				<button class="btn btn-xs" on:click={load}>Retry</button>
			</div>
		{:else}
			<label class="flex items-center gap-2 text-xs cursor-pointer">
				<input
					type="checkbox"
					class="checkbox checkbox-xs rounded-none"
					bind:checked={contextualRetrievalEnabled}
					on:change={handleContextualRetrievalToggle}
				/>
				<span>Contextual retrieval</span>
				<span class="text-base-content/50">(LLM-generated context per chunk during ingestion)</span>
			</label>
			{#if settingsUpdateError}
				<div class="alert alert-error text-xs py-1 px-2 mt-1">
					Change not saved: {settingsUpdateError}
				</div>
			{/if}
		{/if}
	</div>

	<!-- API Keys Section -->
	<div class="bg-base-200 rounded p-2">
		<div class="text-xs font-semibold mb-2 text-base-content/70">API Keys</div>

		{#if loading}
			<div class="text-xs text-base-content/60">Loading...</div>
		{:else if apiKeysLoadError}
			<div class="alert alert-error text-xs py-1 px-2 flex items-center gap-2">
				<span class="flex-1">Could not load API key status: {apiKeysLoadError}</span>
				<button class="btn btn-xs" on:click={load}>Retry</button>
			</div>
		{:else if apiKeyStatuses.length === 0}
			<div class="text-xs text-base-content/60">No API keys required</div>
		{:else}
			<div class="flex flex-col gap-2">
				{#each apiKeyStatuses as status}
					<div class="flex flex-col gap-1">
						<div class="flex items-center gap-2">
							<label class="text-xs font-medium w-20 capitalize">{status.provider}</label>
							<div class="relative flex-1">
								<input
									type="text"
									class="input input-xs w-full {validationErrors[status.provider]
										? 'input-error'
										: ''}"
									placeholder="Enter API key"
									bind:value={apiKeyInputs[status.provider]}
									on:blur={() => handleApiKeySubmit(status.provider)}
									on:keydown={(e) => handleKeyDown(e, status.provider)}
									on:input={() => handleInput(status.provider)}
									disabled={validatingProvider === status.provider}
								/>
								{#if validatingProvider === status.provider}
									<span class="loading loading-spinner loading-xs absolute right-2 top-1/2 -translate-y-1/2"></span>
								{:else if validationSuccess[status.provider]}
									<span class="absolute right-2 top-1/2 -translate-y-1/2 text-success text-sm">✓</span>
								{/if}
							</div>
						</div>
						{#if validationErrors[status.provider]}
							<div class="alert alert-error text-xs py-1 px-2">
								{validationErrors[status.provider]}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
