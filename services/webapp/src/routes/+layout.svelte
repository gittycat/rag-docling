<script lang="ts">
	import '../app.css';
	import ChatSidebar from '$lib/components/ChatSidebar.svelte';
	import { page } from '$app/stores';

	let { children } = $props();

	const isChatPage = $derived($page.url.pathname === '/chat');
	const isUploadPage = $derived($page.url.pathname === '/upload');

	// Page titles for non-chat pages
	const pageTitle = $derived(() => {
		const path = $page.url.pathname;
		switch (path) {
			case '/upload':
				return 'Upload';
			case '/documents':
				return 'Documents';
			case '/dashboard':
				return 'Dashboard';
			case '/settings':
				return 'Settings';
			default:
				return null;
		}
	});
</script>

<div class="min-h-screen bg-base-100 flex">
	<!-- Sidebar - always visible on all pages -->
	<ChatSidebar />

	<!-- Main content area -->
	<div class="flex-1 flex flex-col min-w-0">
		<!-- Global header for non-chat pages -->
		{#if !isChatPage}
			<header class="flex items-center gap-3 border-b border-base-300 px-6 py-4">
				{#if isUploadPage}
					<a href="/documents" class="btn btn-ghost btn-sm btn-square" title="Back to Documents">
						<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
						</svg>
					</a>
				{/if}
				<h1 class="text-lg font-semibold">{pageTitle()}</h1>
			</header>
		{/if}
		<main class="flex-1 {isChatPage ? '' : 'container mx-auto p-4'}">
			{@render children()}
		</main>
	</div>
</div>
