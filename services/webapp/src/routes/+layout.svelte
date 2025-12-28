<script lang="ts">
	import '../app.css';
	import ChatSidebar from '$lib/components/ChatSidebar.svelte';
	import { page } from '$app/stores';

	let { children } = $props();

	const isChatPage = $derived($page.url.pathname === '/chat');
</script>

<div class="min-h-screen bg-base-100 flex">
	<!-- Sidebar - always visible on all pages -->
	<ChatSidebar />

	<!-- Main content area -->
	<div class="flex-1 flex flex-col min-w-0">
		<main class="flex-1 {isChatPage ? '' : 'container mx-auto p-4'}">
			{@render children()}
		</main>
	</div>
</div>
