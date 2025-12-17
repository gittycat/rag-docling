<script lang="ts">
	import { browser } from '$app/environment';
	import { onMount } from 'svelte';
	import {
		streamQuery,
		clearChatSession,
		getDocumentDownloadUrl,
		type ChatMessage,
		type ChatSource
	} from '$lib/api';

	// State
	let messages = $state<ChatMessage[]>([]);
	let sessionId = $state<string>(crypto.randomUUID());
	let inputText = $state('');
	let isStreaming = $state(false);
	let currentStreamingContent = $state('');
	let error = $state<string | null>(null);
	let messagesContainer: HTMLDivElement | undefined = $state();

	// Scroll to bottom when messages change
	$effect(() => {
		if (messagesContainer && (messages.length > 0 || currentStreamingContent)) {
			messagesContainer.scrollTop = messagesContainer.scrollHeight;
		}
	});

	// Persist session ID in localStorage
	$effect(() => {
		if (browser && sessionId) {
			localStorage.setItem('chat_session_id', sessionId);
		}
	});

	// Restore session on mount
	onMount(() => {
		const stored = localStorage.getItem('chat_session_id');
		if (stored) {
			sessionId = stored;
		}
	});

	async function sendMessage() {
		if (!inputText.trim() || isStreaming) return;

		const userMessage = inputText.trim();
		messages = [...messages, { role: 'user', content: userMessage }];
		inputText = '';
		isStreaming = true;
		currentStreamingContent = '';
		error = null;

		try {
			for await (const event of streamQuery(userMessage, sessionId)) {
				if (event.event === 'token') {
					currentStreamingContent += event.data.token;
				} else if (event.event === 'sources') {
					// Add completed message with sources
					messages = [
						...messages,
						{
							role: 'assistant',
							content: currentStreamingContent,
							sources: event.data.sources,
							timestamp: new Date().toISOString()
						}
					];
					sessionId = event.data.session_id;
				} else if (event.event === 'error') {
					error = event.data.error;
				}
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'An error occurred';
			// Add error message to chat
			if (currentStreamingContent) {
				messages = [
					...messages,
					{
						role: 'assistant',
						content: currentStreamingContent + '\n\n[Error: Connection interrupted]'
					}
				];
			}
		} finally {
			isStreaming = false;
			currentStreamingContent = '';
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			sendMessage();
		}
	}

	async function newChat() {
		// Clear server-side session
		try {
			await clearChatSession(sessionId);
		} catch {
			// Ignore errors - session might not exist
		}

		// Reset local state
		messages = [];
		sessionId = crypto.randomUUID();
		inputText = '';
		error = null;
	}

	function saveChat() {
		if (messages.length === 0) return;

		const chatData = {
			session_id: sessionId,
			exported_at: new Date().toISOString(),
			messages: messages.map((m) => ({
				role: m.role,
				content: m.content,
				sources: m.sources?.map((s) => ({
					document_name: s.document_name,
					document_id: s.document_id,
					excerpt: s.excerpt
				})),
				timestamp: m.timestamp
			}))
		};

		const blob = new Blob([JSON.stringify(chatData, null, 2)], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `chat-${sessionId.slice(0, 8)}-${Date.now()}.json`;
		a.click();
		URL.revokeObjectURL(url);
	}

	// Deduplicate sources by document_id
	function getUniqueSources(sources: ChatSource[]): ChatSource[] {
		const seen = new Set<string>();
		return sources.filter((s) => {
			if (!s.document_id || seen.has(s.document_id)) return false;
			seen.add(s.document_id);
			return true;
		});
	}
</script>

<div class="flex h-[calc(100vh-140px)] flex-col">
	<!-- Header with actions -->
	<div class="flex items-center justify-between border-b border-base-300 p-4">
		<div>
			<h2 class="text-lg font-semibold">Chat</h2>
			<p class="text-xs text-base-content/60">Session: {sessionId.slice(0, 8)}...</p>
		</div>
		<div class="flex gap-2">
			<button class="btn btn-outline btn-sm" onclick={newChat} disabled={isStreaming}>
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
						d="M12 4v16m8-8H4"
					/>
				</svg>
				New Chat
			</button>
			<button
				class="btn btn-outline btn-sm"
				onclick={saveChat}
				disabled={isStreaming || messages.length === 0}
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
						d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
					/>
				</svg>
				Save Chat
			</button>
		</div>
	</div>

	<!-- Error alert -->
	{#if error}
		<div class="alert alert-error m-4">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				class="h-6 w-6 shrink-0 stroke-current"
				fill="none"
				viewBox="0 0 24 24"
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

	<!-- Messages area -->
	<div bind:this={messagesContainer} class="flex-1 space-y-4 overflow-y-auto p-4">
		{#if messages.length === 0 && !isStreaming}
			<div class="flex h-full flex-col items-center justify-center text-base-content/50">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					class="mb-4 h-16 w-16"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="1"
						d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
					/>
				</svg>
				<p class="text-lg">Start a conversation</p>
				<p class="text-sm">Ask questions about your documents</p>
			</div>
		{/if}

		{#each messages as message, index (index)}
			<div class="chat {message.role === 'user' ? 'chat-end' : 'chat-start'}">
				<div class="chat-header mb-1">
					{message.role === 'user' ? 'You' : 'Assistant'}
					{#if message.timestamp}
						<time class="text-xs opacity-50">
							{new Date(message.timestamp).toLocaleTimeString()}
						</time>
					{/if}
				</div>
				<div
					class="chat-bubble {message.role === 'user' ? 'chat-bubble-primary' : ''} whitespace-pre-wrap"
				>
					{message.content}
				</div>

				<!-- Sources (assistant messages only) -->
				{#if message.role === 'assistant' && message.sources && message.sources.length > 0}
					{@const uniqueSources = getUniqueSources(message.sources)}
					{#if uniqueSources.length > 0}
						<div class="chat-footer mt-2">
							<div class="text-xs opacity-70">Sources:</div>
							<div class="mt-1 flex flex-wrap gap-1">
								{#each uniqueSources as source (source.document_id)}
									{#if source.document_id}
										<a
											href={getDocumentDownloadUrl(source.document_id)}
											class="badge badge-outline badge-sm transition-colors hover:badge-primary"
											target="_blank"
											title={source.excerpt}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												class="mr-1 h-3 w-3"
												fill="none"
												viewBox="0 0 24 24"
												stroke="currentColor"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"
												/>
											</svg>
											{source.document_name}
										</a>
									{:else}
										<span class="badge badge-ghost badge-sm" title={source.excerpt}>
											{source.document_name}
										</span>
									{/if}
								{/each}
							</div>
						</div>
					{/if}
				{/if}
			</div>
		{/each}

		<!-- Streaming message -->
		{#if isStreaming}
			<div class="chat chat-start">
				<div class="chat-header mb-1">Assistant</div>
				<div class="chat-bubble whitespace-pre-wrap">
					{#if currentStreamingContent}
						{currentStreamingContent}
					{/if}
					<span class="loading loading-dots loading-xs ml-1"></span>
				</div>
			</div>
		{/if}
	</div>

	<!-- Input area -->
	<div class="bg-base-200 p-4">
		<div class="join w-full">
			<input
				type="text"
				placeholder="Type your message..."
				class="input join-item input-bordered flex-1"
				bind:value={inputText}
				onkeydown={handleKeydown}
				disabled={isStreaming}
			/>
			<button
				class="btn btn-primary join-item"
				onclick={sendMessage}
				disabled={isStreaming || !inputText.trim()}
			>
				{#if isStreaming}
					<span class="loading loading-spinner loading-sm"></span>
				{:else}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-5 w-5"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
						/>
					</svg>
				{/if}
			</button>
		</div>
	</div>
</div>
