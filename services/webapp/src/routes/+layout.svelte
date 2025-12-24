<script lang="ts">
	import '../app.css';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
	import ChatSidebar from '$lib/components/ChatSidebar.svelte';
	import { page } from '$app/stores';
	import { openSidebar } from '$lib/stores/sidebar';

	let { children } = $props();

	let isChatPage = $derived($page.url.pathname === '/chat');
</script>

<div class="min-h-screen bg-base-100">
	<ChatSidebar />

	<div class="navbar bg-base-200 shadow-lg">
		<div class="flex-none">
			{#if isChatPage}
				<button
					class="btn btn-ghost btn-square"
					onclick={openSidebar}
					aria-label="Open chat sessions"
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
					</svg>
				</button>
			{/if}
		</div>
		<div class="flex-1">
			<a href="/" class="btn btn-ghost text-xl">RAG Mini Lab</a>
		</div>
		<div class="flex-none">
			<ul class="menu menu-horizontal px-1">
				<li><a href="/chat">Chat</a></li>
				<li><a href="/upload">Upload</a></li>
				<li><a href="/documents">Documents</a></li>
				<li><a href="/dashboard">Dashboard</a></li>
				<li>
					<ThemeToggle />
				</li>
			</ul>
		</div>
	</div>

	<main class="container mx-auto p-4">
		{@render children()}
	</main>
</div>
