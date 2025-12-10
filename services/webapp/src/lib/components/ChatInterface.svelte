<script lang="ts">
	import { onMount } from 'svelte';
	import { chatStore } from '$lib/stores/chat';
	import { sendQuery } from '$lib/utils/api';
	import { getSessionId } from '$lib/utils/session';
	import { Send } from 'lucide-svelte';
	import ChatMessage from './chat/ChatMessage.svelte';

	let query = $state('');
	let sessionId = $state('');
	let messagesContainer: HTMLDivElement;

	onMount(() => {
		sessionId = getSessionId();
	});

	async function handleSubmit() {
		if (!query.trim() || $chatStore.isLoading) return;

		const userMessage = query.trim();
		query = '';

		chatStore.addMessage({ role: 'user', content: userMessage });
		chatStore.setLoading(true);

		setTimeout(scrollToBottom, 0);

		try {
			const response = await sendQuery(userMessage, sessionId);
			chatStore.addMessageWithSources(response.answer, response.sources);
			setTimeout(scrollToBottom, 0);
		} catch (error) {
			chatStore.setError(error instanceof Error ? error.message : 'Failed to send query');
		} finally {
			chatStore.setLoading(false);
		}
	}

	function scrollToBottom() {
		if (messagesContainer) {
			messagesContainer.scrollTop = messagesContainer.scrollHeight;
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			handleSubmit();
		}
	}
</script>

<div class="flex flex-col h-full bg-surface">
	<!-- Messages container -->
	<div bind:this={messagesContainer} class="flex-1 overflow-y-auto p-4 space-y-4">
		{#if $chatStore.messages.length === 0}
			<div class="flex flex-col items-center justify-center h-full px-4 space-y-6">
				<h1 class="text-4xl md:text-5xl font-semibold text-primary text-center">
					g'day, ask me about your docs
				</h1>
				<div class="max-w-2xl space-y-3">
					<p class="text-on-surface-muted text-center text-sm md:text-base">
						I can help you find information across your documents. Try asking questions like:
					</p>
					<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
						<div class="p-4 bg-surface-raised border border-default rounded-lg">
							<p class="text-muted text-sm">"What are the main topics covered?"</p>
						</div>
						<div class="p-4 bg-surface-raised border border-default rounded-lg">
							<p class="text-muted text-sm">"Summarize the key points"</p>
						</div>
						<div class="p-4 bg-surface-raised border border-default rounded-lg">
							<p class="text-muted text-sm">"Find information about..."</p>
						</div>
						<div class="p-4 bg-surface-raised border border-default rounded-lg">
							<p class="text-muted text-sm">"Compare different sections"</p>
						</div>
					</div>
				</div>
			</div>
		{:else}
			{#each $chatStore.messages as message, i (i)}
				<ChatMessage {message} />
			{/each}

			{#if $chatStore.isLoading}
				<div class="flex">
					<div class="max-w-[70%] rounded-lg px-4 py-3 bg-surface-raised border border-default">
						<div class="flex gap-2">
							<div class="w-2 h-2 bg-muted rounded-full animate-bounce"></div>
							<div class="w-2 h-2 bg-muted rounded-full animate-bounce" style="animation-delay: 0.1s"></div>
							<div class="w-2 h-2 bg-muted rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
						</div>
					</div>
				</div>
			{/if}
		{/if}
	</div>

	<!-- Error message -->
	{#if $chatStore.error}
		<div class="mx-4 p-3 bg-red-900/20 border border-red-500/50 text-red-400 rounded">
			{$chatStore.error}
		</div>
	{/if}

	<!-- Input area -->
	<div class="p-4 pb-6">
		<div class="flex gap-3 items-end max-w-3xl mx-auto">
			<div class="flex-1 relative">
				<textarea
					bind:value={query}
					onkeydown={handleKeydown}
					placeholder="Message..."
					rows="1"
					class="w-full px-4 py-3 pr-12 rounded-3xl resize-none focus:outline-none transition
						bg-surface-raised text-on-surface border-2 border-default
						focus:border-primary placeholder:text-muted"
					disabled={$chatStore.isLoading}
				></textarea>
				<button
					onclick={handleSubmit}
					disabled={!query.trim() || $chatStore.isLoading}
					aria-label="Send message"
					class="absolute right-2 bottom-2 w-8 h-8 flex items-center justify-center rounded-full transition
						bg-primary hover:bg-primary-hover disabled:bg-surface-sunken disabled:text-muted
						disabled:cursor-not-allowed text-white"
				>
					<Send class="w-4 h-4" />
				</button>
			</div>
		</div>
	</div>
</div>
