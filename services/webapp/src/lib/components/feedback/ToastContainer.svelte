<script lang="ts">
	import { toast } from '$lib/stores/toast.svelte';
	import Toast from './Toast.svelte';
</script>

{#if toast.items.length > 0}
	<div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
		{#each toast.items as t (t.id)}
			<Toast
				id={t.id}
				type={t.type}
				message={t.message}
				onClose={(id) => toast.remove(id)}
			/>
		{/each}
	</div>
{/if}
