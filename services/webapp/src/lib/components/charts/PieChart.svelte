<script lang="ts">
	import { pie, arc, type PieArcDatum } from 'd3-shape';
	import { scaleOrdinal } from 'd3-scale';

	interface DataPoint {
		label: string;
		value: number;
		color?: string;
	}

	interface Props {
		data: DataPoint[];
		size?: number;
		donut?: boolean;
		showLabels?: boolean;
		showLegend?: boolean;
	}

	let { data, size = 200, donut = false, showLabels = false, showLegend = true }: Props = $props();

	const colors = [
		'rgb(59, 130, 246)', // blue-500
		'rgb(168, 85, 247)', // purple-500
		'rgb(34, 197, 94)', // green-500
		'rgb(251, 146, 60)', // orange-400
		'rgb(236, 72, 153)', // pink-500
		'rgb(20, 184, 166)' // teal-500
	];

	const colorScale = $derived(
		scaleOrdinal<string>()
			.domain(data.map((d) => d.label))
			.range(colors)
	);

	const pieGenerator = pie<DataPoint>()
		.value((d) => d.value)
		.sort(null);

	const pieData = $derived(pieGenerator(data));

	const outerRadius = $derived(size / 2 - 10);
	const innerRadius = $derived(donut ? outerRadius * 0.6 : 0);

	const arcGenerator = $derived(
		arc<PieArcDatum<DataPoint>>().innerRadius(innerRadius).outerRadius(outerRadius)
	);

	const total = $derived(data.reduce((sum, d) => sum + d.value, 0));
</script>

<div class="flex flex-col items-center">
	<svg width={size} height={size} class="overflow-visible">
		<g transform="translate({size / 2}, {size / 2})">
			{#each pieData as slice, i}
				<path
					d={arcGenerator(slice) || ''}
					fill={slice.data.color || colorScale(slice.data.label)}
					class="hover:opacity-80 transition-opacity cursor-pointer"
				>
					<title
						>{slice.data.label}: {slice.data.value} ({((slice.data.value / total) * 100).toFixed(
							1
						)}%)</title
					>
				</path>
			{/each}

			{#if showLabels}
				{#each pieData as slice}
					{@const centroid = arcGenerator.centroid(slice)}
					<text
						x={centroid[0]}
						y={centroid[1]}
						text-anchor="middle"
						dominant-baseline="middle"
						class="fill-white text-xs font-medium pointer-events-none"
					>
						{((slice.data.value / total) * 100).toFixed(0)}%
					</text>
				{/each}
			{/if}
		</g>
	</svg>

	{#if showLegend}
		<div class="flex flex-wrap justify-center gap-4 mt-4">
			{#each data as item, i}
				<div class="flex items-center gap-2 text-sm">
					<div
						class="w-3 h-3 rounded-full"
						style="background-color: {item.color || colors[i % colors.length]}"
					></div>
					<span class="text-muted">{item.label}</span>
					<span class="font-medium text-on-surface">{item.value}</span>
				</div>
			{/each}
		</div>
	{/if}
</div>
