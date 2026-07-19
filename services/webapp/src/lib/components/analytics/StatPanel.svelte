<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Health } from '$lib/utils/stageHealth';
	import HealthBadge from './HealthBadge.svelte';
	import InfoTip from './InfoTip.svelte';

	interface Props {
		label: string;
		value: string;
		/** Threshold band — drives the left accent and (optionally) the badge. */
		health?: Health;
		/** Show the accessible traffic-light badge (color + shape + word). */
		showBadge?: boolean;
		tip?: string;
		/** One comparison line (Vercel card rule: label + value + one comparison). */
		delta?: string | null;
		deltaClass?: string;
		/** Larger treatment for the single most-important panel (top-left). */
		emphasis?: boolean;
		children?: Snippet;
	}

	let {
		label,
		value,
		health = 'unknown',
		showBadge = false,
		tip,
		delta = null,
		deltaClass = '',
		emphasis = false,
		children
	}: Props = $props();

	const ACCENT: Record<Health, string> = {
		good: 'border-l-success',
		warn: 'border-l-warning',
		bad: 'border-l-error',
		unknown: 'border-l-base-content/20'
	};
</script>

<div class="term-panel border-l-4 {ACCENT[health]} flex flex-col gap-1 h-full">
	<div class="flex items-center justify-between gap-1">
		<span class="term-label inline-flex items-center gap-1">
			{label}
			{#if tip}<InfoTip text={tip} />{/if}
		</span>
		{#if showBadge}
			<HealthBadge {health} />
		{/if}
	</div>
	<div class="font-mono tabular-nums leading-none {emphasis ? 'text-3xl' : 'text-2xl'}">
		{value}
	</div>
	{#if delta}
		<div class="font-mono tabular-nums text-xs {deltaClass}">{delta}</div>
	{:else}
		<div class="text-xs text-base-content/30 font-mono">—</div>
	{/if}
	{#if children}
		{@render children()}
	{/if}
</div>
