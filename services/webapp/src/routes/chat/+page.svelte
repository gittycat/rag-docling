<script lang="ts">
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onMount, onDestroy } from 'svelte';
	import {
		streamQuery,
		clearChatSession,
		getChatHistory,
		getDocumentDownloadUrl,
		createNewSession,
		type ChatMessage,
		type ChatSource
	} from '$lib/api';
	import { exportChatFn, canExportChat } from '$lib/stores/chat';
	import { triggerSessionRefresh } from '$lib/stores/sidebar';

	// State
	let messages = $state<ChatMessage[]>([]);
	let sessionId = $state<string | null>(null);
	let sessionTitle = $state<string | null>(null);
	let inputText = $state('');
	let isStreaming = $state(false);
	let isLoadingHistory = $state(false);
	let currentStreamingContent = $state('');
	let error = $state<string | null>(null);
	let messagesContainer: HTMLDivElement | undefined = $state();
	let abortController: AbortController | null = $state(null);
	let textareaElement: HTMLTextAreaElement | undefined = $state();

	// Track current session from URL
	let urlSessionId = $derived($page.url.searchParams.get('session_id'));
	let isTemporaryChat = $derived(!urlSessionId);

	// Load session when URL changes
	$effect(() => {
		if (browser) {
			loadSession(urlSessionId);
		}
	});

	// Scroll to bottom when messages change
	$effect(() => {
		if (messagesContainer && (messages.length > 0 || currentStreamingContent)) {
			messagesContainer.scrollTop = messagesContainer.scrollHeight;
		}
	});

	// Update export store when messages change
	$effect(() => {
		canExportChat.set(messages.length > 0 && !isStreaming);
	});

	// Set export function for sidebar
	onMount(() => {
		exportChatFn.set(saveChat);
	});

	onDestroy(() => {
		exportChatFn.set(null);
		canExportChat.set(false);
	});

	async function loadSession(newSessionId: string | null) {
		// Reset state
		messages = [];
		currentStreamingContent = '';
		error = null;
		sessionTitle = null;
		sessionId = newSessionId;

		// Load history if we have a session ID
		if (newSessionId) {
			isLoadingHistory = true;
			try {
				const history = await getChatHistory(newSessionId);
				messages = history.messages;
				sessionTitle = history.metadata?.title || null;
			} catch (err) {
				console.error('Failed to load session history:', err);
				error = err instanceof Error ? err.message : 'Failed to load session history';
			} finally {
				isLoadingHistory = false;
			}
		}
	}

	async function sendMessage() {
		if (!inputText.trim() || isStreaming) return;

		const userMessage = inputText.trim();
		messages = [...messages, { role: 'user', content: userMessage }];
		inputText = '';
		isStreaming = true;
		currentStreamingContent = '';
		error = null;

		// Create new AbortController for this request
		abortController = new AbortController();

		// If this is a temporary chat, create session immediately before streaming
		// This ensures the chat appears in "Recent" right when user presses Enter
		let currentSessionId = sessionId;
		if (isTemporaryChat) {
			try {
				const newSession = await createNewSession(userMessage);
				currentSessionId = newSession.session_id;
				sessionId = newSession.session_id;
				sessionTitle = newSession.title;

				// Update URL and refresh sidebar immediately
				await goto(`/chat?session_id=${newSession.session_id}`, { replaceState: true });
				triggerSessionRefresh();
			} catch (e) {
				error = e instanceof Error ? e.message : 'Failed to create session';
				isStreaming = false;
				return;
			}
		}

		try {
			// Now stream the query with the established session
			for await (const event of streamQuery(userMessage, currentSessionId, false, abortController.signal)) {
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
				} else if (event.event === 'error') {
					error = event.data.error;
				}
			}
		} catch (e) {
			// Check if this was a user-initiated cancellation
			if (e instanceof Error && e.name === 'AbortError') {
				// Add partial response if any content was streamed
				if (currentStreamingContent) {
					messages = [
						...messages,
						{
							role: 'assistant',
							content: currentStreamingContent + '\n\n[Cancelled]',
							timestamp: new Date().toISOString()
						}
					];
				}
			} else {
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
			}
		} finally {
			isStreaming = false;
			currentStreamingContent = '';
			abortController = null;
		}
	}

	function cancelStream() {
		if (abortController) {
			abortController.abort();
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			sendMessage();
		}
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

<div class="relative flex h-[calc(100vh-68px)] flex-col">
	<!-- Header with actions -->
	<div class="flex items-center justify-between border-b border-base-300 px-6 py-4">
		<div class="flex-1 min-w-0">
			{#if isLoadingHistory}
				<div class="flex items-center gap-2">
					<span class="loading loading-spinner loading-sm"></span>
					<span class="text-sm text-base-content/60">Loading session...</span>
				</div>
			{:else}
				<h2 class="text-lg font-semibold truncate">
					{sessionTitle || (isTemporaryChat ? 'Temporary Chat' : 'Chat')}
				</h2>
				<p class="text-xs text-base-content/60">
					{#if isTemporaryChat}
						Not saved · Messages will be lost when you leave
					{:else if sessionId}
						Session: {sessionId.slice(0, 8)}...
					{/if}
				</p>
			{/if}
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
	<div bind:this={messagesContainer} class="flex-1 space-y-4 overflow-y-auto px-6 py-4">

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
	<div class="px-6 py-4 {messages.length === 0 && !isStreaming ? 'absolute bottom-1/3 left-0 right-0' : ''}">
		<div class="relative w-full max-w-4xl mx-auto">
			<textarea
				bind:this={textareaElement}
				placeholder="Type your message..."
				class="textarea w-full bg-base-200 rounded-3xl py-4 px-5 pr-16 min-h-[60px] max-h-[200px] resize-none border-base-300 focus:border-primary focus:outline-none"
				bind:value={inputText}
				onkeydown={handleKeydown}
				disabled={isStreaming}
				rows="1"
				oninput={(e) => {
					const target = e.currentTarget;
					target.style.height = 'auto';
					target.style.height = Math.min(target.scrollHeight, 200) + 'px';
				}}
			></textarea>
			<!-- Submit/Stop button inside the box -->
			<button
				class="absolute right-3 bottom-3 btn btn-circle btn-sm {isStreaming ? 'btn-neutral' : inputText.trim() ? 'btn-primary' : 'bg-base-300 text-base-content/40 border-none'}"
				onclick={isStreaming ? cancelStream : sendMessage}
				disabled={!isStreaming && !inputText.trim()}
			>
				{#if isStreaming}
					<!-- Stop icon (square) -->
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-4 w-4"
						fill="currentColor"
						viewBox="0 0 24 24"
					>
						<rect x="6" y="6" width="12" height="12" rx="2" />
					</svg>
				{:else}
					<!-- Arrow up icon -->
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-4 w-4"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M5 10l7-7m0 0l7 7m-7-7v18"
						/>
					</svg>
				{/if}
			</button>
		</div>
	</div>
</div>
