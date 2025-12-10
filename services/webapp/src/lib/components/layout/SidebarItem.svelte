<script lang="ts">
	import type { ComponentType } from 'svelte';

	interface Props {
		href: string;
		icon: ComponentType;
		label: string;
		active?: boolean;
		collapsed?: boolean;
	}

	let { href, icon: Icon, label, active = false, collapsed = false }: Props = $props();
</script>

<a
	{href}
	class="flex items-center gap-3 px-3 py-2 rounded-lg transition-colors
				 {active
		? 'bg-sidebar-active text-white'
		: 'text-sidebar-text hover:bg-sidebar-hover'}"
	title={collapsed ? label : undefined}
>
	<Icon class="w-5 h-5 shrink-0" />
	{#if !collapsed}
		<span class="text-sm font-medium">{label}</span>
	{/if}
</a>
