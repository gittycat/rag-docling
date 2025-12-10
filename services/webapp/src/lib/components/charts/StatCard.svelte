<script lang="ts">
	import { Chart, Svg, Area } from 'layerchart';
	import { scaleTime, scaleLinear } from 'd3-scale';
	import type { ComponentType } from 'svelte';

	interface SparklinePoint {
		date: Date;
		value: number;
	}

	interface Props {
		title: string;
		value: string | number;
		subtitle?: string;
		trend?: number;
		sparklineData?: SparklinePoint[];
		icon?: ComponentType;
	}

	let { title, value, subtitle, trend, sparklineData, icon: Icon }: Props = $props();

	const trendColor = $derived(
		trend && trend > 0
			? 'text-green-500'
			: trend && trend < 0
				? 'text-red-500'
				: 'text-muted'
	);
	const trendIcon = $derived(trend && trend > 0 ? '+' : '');
</script>

<div class="bg-surface-raised rounded-lg p-4 border border-default">
	<div class="flex items-start justify-between mb-2">
		<div class="flex items-center gap-2">
			{#if Icon}
				<Icon class="w-4 h-4 text-muted" />
			{/if}
			<span class="text-sm text-muted">{title}</span>
		</div>
		{#if trend !== undefined}
			<span class="text-xs {trendColor}">
				{trendIcon}{trend}%
			</span>
		{/if}
	</div>

	<div class="text-2xl font-semibold text-on-surface mb-1">
		{value}
	</div>

	{#if subtitle}
		<div class="text-xs text-subtle">{subtitle}</div>
	{/if}

	{#if sparklineData && sparklineData.length > 1}
		<div class="h-12 mt-3">
			<Chart
				data={sparklineData}
				x="date"
				xScale={scaleTime()}
				y="value"
				yScale={scaleLinear()}
				yNice
				padding={{ top: 4, bottom: 4, left: 0, right: 0 }}
			>
				<Svg>
					<Area class="fill-blue-500/20" line={{ class: 'stroke-blue-500 stroke-2' }} />
				</Svg>
			</Chart>
		</div>
	{/if}
</div>
