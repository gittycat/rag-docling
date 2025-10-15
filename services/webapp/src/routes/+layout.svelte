<script lang="ts">
	import Header from '$lib/components/Header.svelte';
	import '../app.css';

	let { children } = $props();
</script>

<div class="min-h-screen flex flex-col bg-gray-50">
	<Header />
	<main class="flex-1 container mx-auto px-4 py-6">
		{@render children()}
	</main>
</div>
