<script lang="ts">
	import '../app.css';
	import ChatSidebar from '$lib/components/ChatSidebar.svelte';
	import { page } from '$app/stores';

	let { children } = $props();

	const isChatPage = $derived($page.url.pathname === '/chat');

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
			<header class="flex items-center border-b border-base-300 px-6 py-4">
				<h1 class="text-lg font-semibold">{pageTitle()}</h1>
			</header>
		{/if}
		<main class="flex-1 {isChatPage ? '' : 'container mx-auto p-4'}">
			{@render children()}
		</main>
	</div>
</div>
