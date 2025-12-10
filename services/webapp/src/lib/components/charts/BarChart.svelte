<script lang="ts">
	import { Chart, Svg, Bars, Axis, Tooltip, Highlight } from 'layerchart';
	import { scaleBand, scaleLinear } from 'd3-scale';

	interface DataPoint {
		label: string;
		value: number;
	}

	interface Props {
		data: DataPoint[];
		height?: number;
		horizontal?: boolean;
		formatValue?: (value: number) => string;
	}

	let {
		data,
		height = 300,
		horizontal = false,
		formatValue = (v: number) => v.toLocaleString()
	}: Props = $props();
</script>

<div class="w-full" style="height: {height}px">
	{#if data.length > 0}
		<Chart
			{data}
			x="label"
			xScale={scaleBand().padding(0.3)}
			y="value"
			yScale={scaleLinear()}
			yNice
			padding={{ top: 20, bottom: 36, left: 48, right: 16 }}
		>
			<Svg>
				<Axis placement="left" grid={{ class: 'stroke-gray-200 dark:stroke-gray-700' }} rule />
				<Axis placement="bottom" rule />
				<Bars class="fill-blue-500 hover:fill-blue-600 transition-colors" />
				<Highlight area />
			</Svg>

			<Tooltip.Root>
				{#snippet children({ data: tooltipData }: { data: DataPoint })}
					<Tooltip.Item label={tooltipData.label} value={formatValue(tooltipData.value)} />
				{/snippet}
			</Tooltip.Root>
		</Chart>
	{:else}
		<div class="flex items-center justify-center h-full text-muted">No data available</div>
	{/if}
</div>
