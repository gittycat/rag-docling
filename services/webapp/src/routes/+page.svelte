<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  onMount(() => {
    goto('/chat');
  });
</script>

<div class="flex justify-center items-center h-64">
  <span class="loading loading-spinner loading-lg"></span>
</div>
