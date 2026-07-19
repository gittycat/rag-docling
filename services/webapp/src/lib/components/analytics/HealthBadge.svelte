<script lang="ts">
	import type { Health } from '$lib/utils/stageHealth';

	interface Props {
		health: Health;
		/** Override the default word (good/weak/critical/no data). */
		label?: string;
		size?: 'sm' | 'md';
	}

	let { health, label, size = 'sm' }: Props = $props();

	// Accessibility: never color-only. Each band gets a distinct shape AND word,
	// so the signal survives greyscale / color-blindness.
	const WORD: Record<Health, string> = {
		good: 'good',
		warn: 'weak',
		bad: 'critical',
		unknown: 'no data'
	};

	const COLOR: Record<Health, string> = {
		good: 'text-success',
		warn: 'text-warning',
		bad: 'text-error',
		unknown: 'text-base-content/40'
	};

	let word = $derived(label ?? WORD[health]);
	let dim = $derived(size === 'md' ? 'h-3 w-3' : 'h-2.5 w-2.5');
</script>

<span class="inline-flex items-center gap-1 {COLOR[health]}" role="img" aria-label="{word} health">
	<!-- Distinct shape per band: circle=good, triangle=weak, square=critical, dash=unknown -->
	<svg class={dim} viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
		{#if health === 'good'}
			<circle cx="6" cy="6" r="5" />
		{:else if health === 'warn'}
			<path d="M6 1 L11 10 L1 10 Z" />
		{:else if health === 'bad'}
			<rect x="1.5" y="1.5" width="9" height="9" rx="1" />
		{:else}
			<rect x="1" y="5" width="10" height="2" rx="1" />
		{/if}
	</svg>
	<span class="font-mono text-[10px] font-semibold uppercase tracking-wider">{word}</span>
</span>
