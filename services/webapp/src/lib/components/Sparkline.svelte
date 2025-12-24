<script lang="ts">
	import sparkline from '@fnando/sparkline';

	interface Props {
		values: number[];
		width?: number;
		height?: number;
		strokeColor?: string;
		fillColor?: string;
	}

	let { values, width = 60, height = 16, strokeColor = 'currentColor', fillColor = 'none' }: Props = $props();

	function sparklineAction(node: SVGSVGElement, data: number[]) {
		function render(vals: number[]) {
			if (vals.length > 0) {
				node.innerHTML = '';
				sparkline(node, vals, {
					strokeWidth: 1.5,
					spotRadius: 0
				});
			}
		}

		render(data);

		return {
			update(newData: number[]) {
				render(newData);
			}
		};
	}
</script>

<svg
	use:sparklineAction={values}
	{width}
	{height}
	class="sparkline"
	style="stroke: {strokeColor}; fill: {fillColor};"
></svg>

<style>
	.sparkline {
		display: inline-block;
		vertical-align: middle;
	}
	.sparkline :global(.sparkline--fill) {
		opacity: 0.1;
	}
	.sparkline :global(.sparkline--line) {
		fill: none;
	}
</style>
