<script lang="ts">
	import '../app.css';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';

	let { children } = $props();
</script>

<div class="min-h-screen bg-base-100">
	<div class="navbar bg-base-200 shadow-lg">
		<div class="flex-1">
			<a href="/" class="btn btn-ghost text-xl">RAG App</a>
		</div>
		<div class="flex-none">
			<ul class="menu menu-horizontal px-1">
				<li><a href="/chat">Chat</a></li>
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
