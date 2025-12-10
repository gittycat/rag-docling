<script lang="ts">
	import { Chart, Svg, Area, Axis, Tooltip, Highlight } from 'layerchart';
	import { scaleTime, scaleLinear } from 'd3-scale';
	import { format } from 'date-fns';

	interface DataPoint {
		date: Date;
		value: number;
		label?: string;
	}

	interface Props {
		data: DataPoint[];
		height?: number;
		xLabel?: string;
		yLabel?: string;
		showGrid?: boolean;
		formatValue?: (value: number) => string;
	}

	let {
		data,
		height = 300,
		xLabel,
		yLabel,
		showGrid = true,
		formatValue = (v: number) => v.toLocaleString()
	}: Props = $props();
</script>

<div class="w-full" style="height: {height}px">
	{#if data.length > 0}
		<Chart
			{data}
			x="date"
			xScale={scaleTime()}
			y="value"
			yScale={scaleLinear()}
			yNice
			padding={{ top: 20, bottom: 36, left: 48, right: 16 }}
		>
			<Svg>
				<Axis
					placement="left"
					grid={showGrid ? { class: 'stroke-gray-200 dark:stroke-gray-700' } : undefined}
					rule
				/>
				<Axis placement="bottom" rule />
				<Area class="fill-blue-500/20" line={{ class: 'stroke-blue-500 stroke-2' }} />
				<Highlight points={{ class: 'fill-blue-500' }} lines />
			</Svg>

			<Tooltip.Root header={(d: DataPoint) => format(d.date, 'MMM d, yyyy')}>
				{#snippet children({ data: tooltipData }: { data: DataPoint })}
					<Tooltip.Item label="Value" value={formatValue(tooltipData.value)} />
				{/snippet}
			</Tooltip.Root>
		</Chart>
	{:else}
		<div class="flex items-center justify-center h-full text-muted">No data available</div>
	{/if}
</div>
