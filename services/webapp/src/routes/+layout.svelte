<script lang="ts">
	import '../app.css';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
	import ChatSidebar from '$lib/components/ChatSidebar.svelte';
	import { page } from '$app/stores';
	import { sidebarOpen } from '$lib/stores/sidebar';

	let { children } = $props();

	let isChatPage = $derived($page.url.pathname === '/chat');
</script>

<div class="min-h-screen bg-base-100 flex">
	<!-- Sidebar - always rendered on chat page, pushes content -->
	{#if isChatPage}
		<ChatSidebar />
	{/if}

	<!-- Main content area -->
	<div class="flex-1 flex flex-col min-w-0">
		<div class="navbar bg-base-200 shadow-lg">
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

		<main class="flex-1 container mx-auto p-4">
			{@render children()}
		</main>
	</div>
</div>
