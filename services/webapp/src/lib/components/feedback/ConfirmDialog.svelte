<script lang="ts">
	import { AlertTriangle } from 'lucide-svelte';

	interface Props {
		open: boolean;
		title: string;
		message: string;
		confirmText?: string;
		cancelText?: string;
		onConfirm: () => void;
		onCancel: () => void;
	}

	let {
		open,
		title,
		message,
		confirmText = 'Confirm',
		cancelText = 'Cancel',
		onConfirm,
		onCancel
	}: Props = $props();
</script>

{#if open}
	<!-- Backdrop -->
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={onCancel}
		onkeydown={(e) => e.key === 'Escape' && onCancel()}
		role="button"
		tabindex="-1"
	>
		<!-- Dialog -->
		<div
			class="bg-surface-raised border border-default rounded-lg shadow-xl max-w-md w-full p-6"
			onclick={(e) => e.stopPropagation()}
			onkeydown={() => {}}
			role="dialog"
			aria-modal="true"
			aria-labelledby="dialog-title"
			tabindex="0"
		>
			<div class="flex items-start gap-4">
				<div class="p-2 rounded-full bg-red-500/20">
					<AlertTriangle class="w-6 h-6 text-red-400" />
				</div>
				<div class="flex-1">
					<h3 id="dialog-title" class="text-lg font-semibold text-on-surface">{title}</h3>
					<p class="mt-2 text-sm text-muted">{message}</p>
				</div>
			</div>

			<div class="flex justify-end gap-3 mt-6">
				<button
					onclick={onCancel}
					class="px-4 py-2 text-sm font-medium text-on-surface bg-surface-sunken
								 hover:bg-surface-overlay rounded-lg transition-colors"
				>
					{cancelText}
				</button>
				<button
					onclick={onConfirm}
					class="px-4 py-2 text-sm font-medium text-white bg-red-600
								 hover:bg-red-700 rounded-lg transition-colors"
				>
					{confirmText}
				</button>
			</div>
		</div>
	</div>
{/if}
