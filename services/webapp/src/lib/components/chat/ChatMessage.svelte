<script lang="ts">
	import type { Message, Source } from '$lib/utils/api';
	import Citation from './Citation.svelte';
	import { ChevronDown, ChevronUp } from 'lucide-svelte';

	interface Props {
		message: Message;
	}

	let { message }: Props = $props();

	let expandedCitations = $state<Set<number>>(new Set());
	let showAllSources = $state(false);

	function toggleCitation(index: number) {
		if (expandedCitations.has(index)) {
			expandedCitations.delete(index);
		} else {
			expandedCitations.add(index);
		}
		expandedCitations = new Set(expandedCitations);
	}

	function parseContentWithCitations(content: string): { text: string; citationIndices: number[] }[] {
		const parts: { text: string; citationIndices: number[] }[] = [];
		const regex = /\[(\d+)\]/g;
		let lastIndex = 0;
		let match;

		while ((match = regex.exec(content)) !== null) {
			if (match.index > lastIndex) {
				parts.push({ text: content.slice(lastIndex, match.index), citationIndices: [] });
			}
			const citationNum = parseInt(match[1], 10);
			parts.push({ text: '', citationIndices: [citationNum] });
			lastIndex = regex.lastIndex;
		}

		if (lastIndex < content.length) {
			parts.push({ text: content.slice(lastIndex), citationIndices: [] });
		}

		return parts;
	}

	const parsedContent = $derived(parseContentWithCitations(message.content));
	const hasSources = $derived(message.sources && message.sources.length > 0);
</script>

<div class="flex" class:justify-end={message.role === 'user'}>
	<div
		class="max-w-[70%] rounded-lg px-4 py-3
			{message.role === 'user'
			? 'bg-primary text-white'
			: 'bg-surface-raised text-on-surface border border-default'}"
	>
		<div class="whitespace-pre-wrap">
			{#each parsedContent as part}
				{#if part.text}
					{part.text}
				{/if}
				{#each part.citationIndices as citationIndex}
					{#if message.sources && message.sources[citationIndex - 1]}
						<Citation
							index={citationIndex}
							source={message.sources[citationIndex - 1]}
							expanded={expandedCitations.has(citationIndex)}
							onToggle={() => toggleCitation(citationIndex)}
						/>
					{:else}
						<span class="text-xs text-muted">[{citationIndex}]</span>
					{/if}
				{/each}
			{/each}
		</div>

		<!-- Sources summary -->
		{#if hasSources && message.role === 'assistant'}
			<div class="mt-3 pt-3 border-t border-default">
				<button
					onclick={() => showAllSources = !showAllSources}
					class="flex items-center gap-1 text-xs text-muted hover:text-on-surface transition-colors"
				>
					{#if showAllSources}
						<ChevronUp class="w-3 h-3" />
					{:else}
						<ChevronDown class="w-3 h-3" />
					{/if}
					{message.sources?.length} source{message.sources?.length === 1 ? '' : 's'}
				</button>

				{#if showAllSources}
					<div class="mt-2 space-y-2">
						{#each message.sources || [] as source, i}
							<Citation
								index={i + 1}
								{source}
								expanded={true}
								onToggle={() => {}}
							/>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
