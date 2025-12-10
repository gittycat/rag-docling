<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	onMount(() => {
		goto('/documents', { replaceState: true });
	});
</script>

<div class="flex items-center justify-center h-screen">
	<p class="text-muted">Redirecting...</p>
</div>
