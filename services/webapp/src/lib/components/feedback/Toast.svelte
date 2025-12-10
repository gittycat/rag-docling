<script lang="ts">
	import { X, CheckCircle, AlertCircle, AlertTriangle, Info } from 'lucide-svelte';
	import type { ToastType } from '$lib/stores/toast.svelte';
	import type { ComponentType } from 'svelte';

	interface Props {
		id: string;
		type: ToastType;
		message: string;
		onClose: (id: string) => void;
	}

	let { id, type, message, onClose }: Props = $props();

	const icons: Record<ToastType, ComponentType> = {
		success: CheckCircle,
		error: AlertCircle,
		warning: AlertTriangle,
		info: Info
	};

	const styles = {
		success: 'bg-green-900/90 border-green-500/50 text-green-100',
		error: 'bg-red-900/90 border-red-500/50 text-red-100',
		warning: 'bg-yellow-900/90 border-yellow-500/50 text-yellow-100',
		info: 'bg-blue-900/90 border-blue-500/50 text-blue-100'
	};

	const iconColors = {
		success: 'text-green-400',
		error: 'text-red-400',
		warning: 'text-yellow-400',
		info: 'text-blue-400'
	};

	const IconComponent = $derived(icons[type]);
</script>

<div
	class="flex items-center gap-3 p-4 rounded-lg border shadow-lg backdrop-blur-sm
				 animate-in slide-in-from-right duration-300 {styles[type]}"
	role="alert"
>
	<IconComponent class="w-5 h-5 shrink-0 {iconColors[type]}" />
	<p class="flex-1 text-sm">{message}</p>
	<button
		onclick={() => onClose(id)}
		class="p-1 rounded hover:bg-white/10 transition-colors"
		aria-label="Close notification"
	>
		<X class="w-4 h-4" />
	</button>
</div>
