<script lang="ts">
	import { LineChart } from 'layerchart';

	interface Props {
		/** Values oldest → newest; nulls render as gaps. */
		values: (number | null)[];
		color?: string;
		height?: number;
	}

	let { values, color = 'var(--color-primary)', height = 40 }: Props = $props();

	let points = $derived(values.map((v, i) => ({ i, value: v })));
	let hasData = $derived(values.some((v) => v != null));
</script>

{#if hasData && values.length > 1}
	<div style="height: {height}px;">
		<LineChart
			data={points}
			x="i"
			y="value"
			series={[{ key: 'value', color }]}
			axis={false}
			grid={false}
			points={false}
			legend={false}
			padding={{ top: 3, bottom: 3, left: 2, right: 2 }}
			props={{ spline: { strokeWidth: 1.5 } }}
		/>
	</div>
{:else}
	<div class="text-[10px] text-base-content/30 font-mono" style="height: {height}px;">
		not enough history
	</div>
{/if}
