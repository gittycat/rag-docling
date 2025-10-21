<script lang="ts">
	import { onMount } from 'svelte';
	import { chatStore } from '$lib/stores/chat';
	import { themeStore } from '$lib/stores/theme';
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

<div class="flex flex-col h-full {$themeStore === 'dark' ? 'bg-gray-900' : 'bg-white'}">
	<!-- Theme toggle button -->
	<div class="absolute top-4 right-4 z-10">
		<button
			onclick={() => themeStore.toggle()}
			aria-label="Toggle theme"
			class="p-2 rounded-lg transition {$themeStore === 'dark'
				? 'bg-gray-800 hover:bg-gray-700 text-yellow-400'
				: 'bg-gray-100 hover:bg-gray-200 text-gray-700'}"
		>
			{#if $themeStore === 'dark'}
				<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
				</svg>
			{:else}
				<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
				</svg>
			{/if}
		</button>
	</div>

	<!-- Messages container -->
	<div bind:this={messagesContainer} class="flex-1 overflow-y-auto p-4 space-y-4">
		{#if $chatStore.messages.length === 0}
			<div class="flex items-center justify-center h-full">
				<h1 class="text-6xl font-semibold {$themeStore === 'dark' ? 'text-blue-400' : 'text-blue-600'}">
					g'day, ask me about your docs
				</h1>
			</div>
		{:else}
			{#each $chatStore.messages as message, i (i)}
				<div class="flex" class:justify-end={message.role === 'user'}>
					<div
						class="max-w-[70%] rounded-lg px-4 py-3 {$themeStore === 'dark'
							? message.role === 'user'
								? 'bg-blue-600 text-white'
								: 'bg-gray-800 text-gray-100'
							: message.role === 'user'
								? 'bg-blue-600 text-white'
								: 'bg-gray-200 text-gray-900'}"
					>
						<p class="whitespace-pre-wrap">{message.content}</p>
					</div>
				</div>
			{/each}

			{#if $chatStore.isLoading}
				<div class="flex">
					<div class="max-w-[70%] rounded-lg px-4 py-3 {$themeStore === 'dark' ? 'bg-gray-800' : 'bg-gray-200'}">
						<div class="flex gap-2">
							<div class="w-2 h-2 {$themeStore === 'dark' ? 'bg-gray-400' : 'bg-gray-600'} rounded-full animate-bounce"></div>
							<div class="w-2 h-2 {$themeStore === 'dark' ? 'bg-gray-400' : 'bg-gray-600'} rounded-full animate-bounce delay-100"></div>
							<div class="w-2 h-2 {$themeStore === 'dark' ? 'bg-gray-400' : 'bg-gray-600'} rounded-full animate-bounce delay-200"></div>
						</div>
					</div>
				</div>
			{/if}
		{/if}
	</div>

	<!-- Error message -->
	{#if $chatStore.error}
		<div class="mx-4 p-3 {$themeStore === 'dark'
			? 'bg-red-900 border border-red-700 text-red-200'
			: 'bg-red-100 border border-red-400 text-red-700'} rounded">
			{$chatStore.error}
		</div>
	{/if}

	<!-- Input area with glow effect -->
	<div class="p-4 pb-6">
		<div class="flex gap-3 items-end max-w-3xl mx-auto">
			<div class="flex-1 relative">
				<textarea
					bind:value={query}
					onkeydown={handleKeydown}
					placeholder="Message..."
					rows="1"
					class="w-full px-4 py-3 pr-12 rounded-3xl resize-none focus:outline-none transition
						{$themeStore === 'dark'
							? 'bg-gray-800 text-gray-100 border-2 border-blue-500/30 focus:border-blue-400/50 shadow-[0_0_10px_rgba(59,130,246,0.3)] focus:shadow-[0_0_20px_rgba(59,130,246,0.5)]'
							: 'bg-white text-gray-900 border-2 border-gray-300 focus:border-blue-400 shadow-sm focus:shadow-md'}"
					disabled={$chatStore.isLoading}
				></textarea>
				<button
					onclick={handleSubmit}
					disabled={!query.trim() || $chatStore.isLoading}
					aria-label="Send message"
					class="absolute right-2 bottom-2 w-8 h-8 flex items-center justify-center rounded-full transition
						{$themeStore === 'dark'
							? 'bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 shadow-[0_0_10px_rgba(37,99,235,0.4)]'
							: 'bg-black hover:bg-gray-800 disabled:bg-gray-300'}
						disabled:cursor-not-allowed"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-4 w-4 text-white"
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
</div>
