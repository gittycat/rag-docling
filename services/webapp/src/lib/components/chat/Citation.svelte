<script lang="ts">
	import type { Source } from '$lib/utils/api';
	import { FileText, ChevronDown, ChevronUp } from 'lucide-svelte';

	interface Props {
		index: number;
		source: Source;
		expanded?: boolean;
		onToggle: () => void;
	}

	let { index, source, expanded = false, onToggle }: Props = $props();
</script>

<span class="inline-block">
	<button
		onclick={onToggle}
		class="inline-flex items-center justify-center w-5 h-5 text-xs font-medium rounded-full
					 bg-primary text-white hover:bg-primary-hover transition-colors cursor-pointer align-top"
		title={source.document_name}
	>
		{index}
	</button>
</span>

{#if expanded}
	<div class="mt-2 p-3 rounded-lg bg-surface-sunken border border-default text-sm">
		<div class="flex items-center gap-2 mb-2">
			<FileText class="w-4 h-4 text-muted" />
			<span class="font-medium text-on-surface">{source.document_name}</span>
		</div>
		<p class="text-muted whitespace-pre-wrap text-xs leading-relaxed">{source.excerpt}</p>
		{#if source.distance != null}
			<div class="mt-2 text-xs text-subtle">
				Relevance: {((1 - source.distance) * 100).toFixed(1)}%
			</div>
		{/if}
	</div>
{/if}
