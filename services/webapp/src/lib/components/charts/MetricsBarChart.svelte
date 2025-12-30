<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { chartAction, getChartColors, formatRunLabel } from './ChartAction';
	import type { EvaluationRun, GoldenBaseline } from '$lib/api';
	import type { ChartConfiguration } from 'chart.js';

	interface Props {
		runs: EvaluationRun[];
		baseline: GoldenBaseline | null;
		height?: number;
	}

	let { runs, baseline, height = 300 }: Props = $props();

	let canvasElement: HTMLCanvasElement | null = $state(null);
	let mounted = $state(false);

	onMount(() => {
		mounted = true;
	});

	// Get all unique metrics across all runs
	let metrics = $derived.by(() => {
		const allMetrics = new Set<string>();
		for (const run of runs) {
			for (const metric of Object.keys(run.metric_averages)) {
				allMetrics.add(metric);
			}
		}
		return Array.from(allMetrics).sort();
	});

	// Format metric names for display
	function formatMetricName(metric: string): string {
		return metric
			.replace(/_/g, ' ')
			.replace(/\b\w/g, (c) => c.toUpperCase());
	}

	// Build Chart.js configuration
	let chartConfig = $derived.by((): ChartConfiguration<'bar'> => {
		const labels = metrics.map(formatMetricName);
		const colors = getChartColors(runs.length);

		// Each run becomes a dataset
		const datasets = runs.map((run, i) => ({
			label: formatRunLabel(run.config_snapshot?.llm_model, run.timestamp),
			data: metrics.map((m) => (run.metric_averages[m] ?? 0) * 100),
			backgroundColor: colors.background[i],
			borderColor: colors.border[i],
			borderWidth: 1
		}));

		// Baseline annotations (horizontal dashed lines)
		const annotations: Record<string, object> = {};
		if (baseline && baseline.target_metrics) {
			// Create a single baseline line at the average of all target metrics
			// Or create per-metric lines with annotation plugin
			let baselineIndex = 0;
			for (const metric of metrics) {
				const targetValue = baseline.target_metrics[metric];
				if (targetValue !== undefined) {
					annotations[`baseline-${metric}`] = {
						type: 'line',
						yMin: targetValue * 100,
						yMax: targetValue * 100,
						borderColor: 'rgba(251, 191, 36, 0.8)', // Amber/warning color
						borderWidth: 2,
						borderDash: [6, 4],
						label: {
							display: baselineIndex === 0,
							content: 'Baseline',
							position: 'start',
							backgroundColor: 'rgba(251, 191, 36, 0.9)',
							color: '#000',
							font: { size: 10 }
						}
					};
					baselineIndex++;
				}
			}
		}

		return {
			type: 'bar',
			data: { labels, datasets },
			options: {
				responsive: true,
				maintainAspectRatio: false,
				scales: {
					y: {
						beginAtZero: true,
						max: 100,
						title: {
							display: true,
							text: 'Score (%)',
							font: { size: 11 }
						},
						ticks: {
							font: { size: 10 }
						}
					},
					x: {
						ticks: {
							font: { size: 10 },
							maxRotation: 45,
							minRotation: 0
						}
					}
				},
				plugins: {
					annotation: {
						annotations
					},
					legend: {
						position: 'bottom',
						labels: {
							boxWidth: 12,
							font: { size: 11 },
							padding: 8
						}
					},
					tooltip: {
						callbacks: {
							label: (ctx) => {
								const value = typeof ctx.raw === 'number' ? ctx.raw.toFixed(1) : '0';
								return `${ctx.dataset.label}: ${value}%`;
							}
						}
					}
				}
			}
		};
	});
</script>

{#if browser && mounted && runs.length > 0}
	<div class="w-full" style="height: {height}px;">
		<canvas bind:this={canvasElement} use:chartAction={chartConfig}></canvas>
	</div>
{:else if runs.length === 0}
	<div class="flex items-center justify-center h-48 text-base-content/50 text-sm">
		Select runs to compare
	</div>
{:else}
	<div class="flex items-center justify-center h-48">
		<span class="loading loading-spinner loading-md"></span>
	</div>
{/if}
