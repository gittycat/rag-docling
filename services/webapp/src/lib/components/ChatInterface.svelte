<script lang="ts">
	import { onMount } from 'svelte';
	import { chatStore } from '$lib/stores/chat';
	import { sendQuery } from '$lib/utils/api';
	import { getSessionId } from '$lib/utils/session';

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
			chatStore.addMessage({ role: 'assistant', content: response.answer });
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

<div class="flex flex-col h-full">
	<!-- Messages container -->
	<div bind:this={messagesContainer} class="flex-1 overflow-y-auto p-4 space-y-4">
		{#if $chatStore.messages.length === 0}
			<div class="flex items-center justify-center h-full text-gray-500">
				<p class="text-xl">Start a conversation by asking a question</p>
			</div>
		{:else}
			{#each $chatStore.messages as message}
				<div class="flex" class:justify-end={message.role === 'user'}>
					<div
						class="max-w-[70%] rounded-lg px-4 py-3"
						class:bg-blue-600={message.role === 'user'}
						class:text-white={message.role === 'user'}
						class:bg-gray-200={message.role === 'assistant'}
						class:text-gray-900={message.role === 'assistant'}
					>
						<p class="whitespace-pre-wrap">{message.content}</p>
					</div>
				</div>
			{/each}

			{#if $chatStore.isLoading}
				<div class="flex">
					<div class="max-w-[70%] rounded-lg px-4 py-3 bg-gray-200">
						<div class="flex gap-2">
							<div class="w-2 h-2 bg-gray-600 rounded-full animate-bounce"></div>
							<div class="w-2 h-2 bg-gray-600 rounded-full animate-bounce delay-100"></div>
							<div class="w-2 h-2 bg-gray-600 rounded-full animate-bounce delay-200"></div>
						</div>
					</div>
				</div>
			{/if}
		{/if}
	</div>

	<!-- Error message -->
	{#if $chatStore.error}
		<div class="mx-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
			{$chatStore.error}
		</div>
	{/if}

	<!-- Input area -->
	<div class="border-t p-4">
		<div class="flex gap-2 items-end">
			<textarea
				bind:value={query}
				onkeydown={handleKeydown}
				placeholder="Ask a question..."
				rows="2"
				class="flex-1 px-4 py-3 border rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
				disabled={$chatStore.isLoading}
			></textarea>
			<button
				onclick={handleSubmit}
				disabled={!query.trim() || $chatStore.isLoading}
				class="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					class="h-6 w-6"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M5 10l7-7m0 0l7 7m-7-7v18"
					/>
				</svg>
			</button>
		</div>
	</div>
</div>
