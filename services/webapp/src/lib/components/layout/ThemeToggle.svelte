<script lang="ts">
	import { Sun, Moon, Monitor } from 'lucide-svelte';
	import { theme, type Theme } from '$lib/stores/theme.svelte';
	import type { ComponentType } from 'svelte';

	interface Props {
		collapsed?: boolean;
	}

	let { collapsed = false }: Props = $props();

	const options: { value: Theme; icon: ComponentType; label: string }[] = [
		{ value: 'light', icon: Sun, label: 'Light' },
		{ value: 'dark', icon: Moon, label: 'Dark' },
		{ value: 'system', icon: Monitor, label: 'System' }
	];

	function cycleTheme() {
		const current = theme.preference;
		const idx = options.findIndex((o) => o.value === current);
		const next = options[(idx + 1) % options.length];
		theme.setPreference(next.value);
	}

	const currentOption = $derived(options.find((o) => o.value === theme.preference) || options[0]);
	const CurrentIcon = $derived(currentOption.icon);
</script>

<button
	onclick={cycleTheme}
	class="flex items-center gap-3 w-full px-3 py-2 rounded-lg transition-colors
				 text-sidebar-text hover:bg-sidebar-hover"
	title={collapsed ? currentOption.label : undefined}
>
	<CurrentIcon class="w-5 h-5 shrink-0" />
	{#if !collapsed}
		<span class="text-sm">{currentOption.label}</span>
	{/if}
</button>
