<script lang="ts">
	import ChatInterface from '$lib/components/ChatInterface.svelte';
	import { themeStore } from '$lib/stores/theme';
</script>

<svelte:head>
	<title>RAG System - Home</title>
</svelte:head>

<div class="h-[calc(100vh-140px)] rounded-lg shadow-lg {$themeStore === 'dark' ? 'bg-gray-900' : 'bg-white'}">
	<ChatInterface />
</div>
