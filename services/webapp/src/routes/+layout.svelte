<script lang="ts">
	import { settings } from 'svelte-ux';
	import { sidebar } from '$lib/stores/sidebar.svelte';
	import Sidebar from '$lib/components/layout/Sidebar.svelte';
	import ToastContainer from '$lib/components/feedback/ToastContainer.svelte';
	import '../app.css';

	// Initialize svelte-ux with theme configuration
	settings({
		themes: {
			light: ['light'],
			dark: ['dark']
		}
	});

	let { children } = $props();
</script>

<div class="min-h-screen bg-surface">
	<Sidebar />
	<main
		class="transition-all duration-200 min-h-screen"
		class:ml-[240px]={!sidebar.collapsed}
		class:ml-16={sidebar.collapsed}
	>
		{@render children()}
	</main>
	<ToastContainer />
</div>
