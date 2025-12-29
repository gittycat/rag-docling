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
	let sessionCreatedAt = $state<string | null>(null);
	let sessionLlmModel = $state<string | null>(null);
	let sessionSearchType = $state<string | null>(null);
	let inputText = $state('');
	let isStreaming = $state(false);
	let isLoadingHistory = $state(false);
	let currentStreamingContent = $state('');
	let error = $state<string | null>(null);
	let messagesContainer: HTMLDivElement | undefined = $state();
	let abortController: AbortController | null = $state(null);
	let textareaElement: HTMLTextAreaElement | undefined = $state();

	// Format UTC date to local date/time string
	function formatLocalDateTime(isoString: string): string {
		const date = new Date(isoString);
		return date.toLocaleString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	// Format search type for display
	function formatSearchType(searchType: string | null): string {
		if (!searchType) return '';
		switch (searchType) {
			case 'hybrid':
				return 'Hybrid (BM25+Vector)';
			case 'vector':
				return 'Vector';
			default:
				return searchType;
		}
	}

	// Track current session from URL
	let urlSessionId = $derived($page.url.searchParams.get('session_id'));
	let isTemporaryMode = $derived($page.url.searchParams.get('temporary') === 'true');
	let isTemporaryChat = $state(false);

	// Track if session has been initialized (first message sent)
	// Chat only appears in sidebar after initialization
	let isInitialized = $state(false);

	// Load or create session when URL changes
	$effect(() => {
		if (browser) {
			handleUrlChange(urlSessionId, isTemporaryMode);
		}
	});

	async function handleUrlChange(newSessionId: string | null, temporary: boolean) {
		if (newSessionId) {
			// Skip reload if we already have this session (e.g., just created it in sendMessage)
			if (newSessionId === sessionId) {
				isTemporaryChat = false;
				isInitialized = true;
				return;
			}
			// Load existing session (already initialized)
			isTemporaryChat = false;
			isInitialized = true;
			await loadSession(newSessionId);
		} else if (temporary) {
			// Explicit temporary mode requested - wait for first message
			isTemporaryChat = true;
			isInitialized = false;
			resetState();
		} else {
			// New chat - don't create session until first message
			// Session will be created in sendMessage() with title from first query
			isTemporaryChat = false;
			isInitialized = false;
			resetState();
		}
	}

	function resetState() {
		messages = [];
		currentStreamingContent = '';
		error = null;
		sessionTitle = null;
		sessionId = null;
		sessionCreatedAt = null;
		sessionLlmModel = null;
		sessionSearchType = null;
	}

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

	// Set export function for sidebar and focus input
	onMount(() => {
		exportChatFn.set(saveChat);
		textareaElement?.focus();
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
		sessionCreatedAt = null;
		sessionLlmModel = null;
		sessionSearchType = null;
		sessionId = newSessionId;

		// Load history if we have a session ID
		if (newSessionId) {
			isLoadingHistory = true;
			try {
				const history = await getChatHistory(newSessionId);
				messages = history.messages;
				// Extract all metadata fields
				if (history.metadata) {
					sessionTitle = history.metadata.title || null;
					sessionCreatedAt = history.metadata.created_at || null;
					sessionLlmModel = history.metadata.llm_model || null;
					sessionSearchType = history.metadata.search_type || null;
				}
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

		// If not initialized and not temporary, create session with first message
		// This ensures the chat appears in "Recent" right when user presses Enter
		let currentSessionId = sessionId;
		if (!isInitialized && !isTemporaryChat) {
			try {
				const newSession = await createNewSession(userMessage);
				currentSessionId = newSession.session_id;
				sessionId = newSession.session_id;
				sessionTitle = newSession.title;
				sessionCreatedAt = newSession.created_at;
				sessionLlmModel = newSession.llm_model || null;
				sessionSearchType = newSession.search_type || null;
				isInitialized = true;

				// Update URL and refresh sidebar so chat appears in Recent
				await goto(`/chat?session_id=${newSession.session_id}`, { replaceState: true });
				triggerSessionRefresh();
			} catch (e) {
				error = e instanceof Error ? e.message : 'Failed to create session';
				isStreaming = false;
				return;
			}
		} else if (!isInitialized && isTemporaryChat) {
			// Temporary chat: mark as initialized but don't create session
			// Messages are not persisted - will be lost when user leaves
			isInitialized = true;
		}

		try {
			// Now stream the query with the established session
			// For temporary chats, pass isTemporary=true so messages aren't persisted
			for await (const event of streamQuery(userMessage, currentSessionId, isTemporaryChat, abortController.signal)) {
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
		<!-- Left side: Title and metadata -->
		<div class="flex-1 min-w-0">
			{#if isLoadingHistory}
				<div class="flex items-center gap-2">
					<span class="loading loading-spinner loading-sm"></span>
					<span class="text-sm text-base-content/60">Loading session...</span>
				</div>
			{:else}
				{#if sessionTitle}
					<h2 class="text-lg font-semibold truncate">{sessionTitle}</h2>
				{/if}
				<div class="flex flex-wrap items-center gap-x-3 gap-y-1 {sessionTitle ? 'mt-1' : ''}">
					{#if isTemporaryChat}
						<span class="text-xs text-warning">Not saved · Messages will be lost when you leave</span>
					{:else if sessionId}
						{#if sessionCreatedAt}
							<span class="text-xs text-base-content/60" title="Created at">
								{formatLocalDateTime(sessionCreatedAt)}
							</span>
						{/if}
						{#if sessionLlmModel}
							<span class="badge badge-ghost badge-xs" title="LLM Model">
								{sessionLlmModel}
							</span>
						{/if}
						{#if sessionSearchType}
							<span class="badge badge-ghost badge-xs" title="Search Type">
								{formatSearchType(sessionSearchType)}
							</span>
						{/if}
					{/if}
				</div>
			{/if}
		</div>

		<!-- Right side: Action buttons -->
		<div class="flex items-center gap-1">
			<!-- New Chat button -->
			<div class="tooltip tooltip-left" data-tip="New chat">
				<button
					class="btn btn-sm btn-square btn-action"
					onclick={() => goto('/chat')}
					disabled={!isInitialized}
					aria-label="New chat"
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125" />
						<path stroke-linecap="round" stroke-linejoin="round" d="M19 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h6" />
					</svg>
				</button>
			</div>

			<!-- Toggle temporary mode (only before first message, locked after initialization) -->
			<div class="tooltip tooltip-left" data-tip="Temporary Mode">
				<button
					class="btn btn-sm btn-square"
					class:btn-action={!isTemporaryChat}
					class:btn-warning={isTemporaryChat}
					onclick={() => goto(isTemporaryChat ? '/chat' : '/chat?temporary=true')}
					disabled={isInitialized}
					aria-label={isTemporaryChat ? 'Switch to persistent chat' : 'Switch to temporary chat'}
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
					</svg>
				</button>
			</div>
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
				placeholder="Query your uploaded documents..."
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
