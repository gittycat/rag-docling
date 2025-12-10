<script lang="ts">
	interface Props {
		rows?: number;
		height?: string;
		className?: string;
	}

	let { rows = 3, height = 'h-16', className = '' }: Props = $props();
</script>

<div class="space-y-3 {className}">
	{#each Array(rows) as _, i}
		<div class="{height} bg-surface-sunken rounded-lg animate-pulse border border-default/50"></div>
	{/each}
</div>

<style>
	@keyframes pulse {
		0%, 100% {
			opacity: 1;
		}
		50% {
			opacity: 0.5;
		}
	}

	.animate-pulse {
		animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
	}
</style>
