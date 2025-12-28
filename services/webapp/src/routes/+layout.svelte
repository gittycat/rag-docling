<script lang="ts">
	import '../app.css';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
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
		<div class="navbar bg-base-200 shadow-lg">
			<div class="flex-1">
				<a href="/" class="btn btn-ghost text-xl">RAG Mini Lab</a>
			</div>
			<div class="flex-none">
				<ThemeToggle />
			</div>
		</div>

		<main class="flex-1 {isChatPage ? '' : 'container mx-auto p-4'}">
			{@render children()}
		</main>
	</div>
</div>
