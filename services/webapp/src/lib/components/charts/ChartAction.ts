/**
 * Svelte action for Chart.js integration
 * Follows the same pattern as Sparkline.svelte but for full Chart.js charts
 */
import {
	Chart,
	CategoryScale,
	LinearScale,
	BarElement,
	BarController,
	Title,
	Tooltip,
	Legend,
	type ChartConfiguration
} from 'chart.js';
import annotationPlugin from 'chartjs-plugin-annotation';

// Register Chart.js components
Chart.register(
	CategoryScale,
	LinearScale,
	BarElement,
	BarController,
	Title,
	Tooltip,
	Legend,
	annotationPlugin
);

/**
 * Svelte action to create and manage a Chart.js instance
 * Usage: <canvas use:chartAction={chartConfig}></canvas>
 */
export function chartAction(
	canvas: HTMLCanvasElement,
	config: ChartConfiguration<'bar'>
): { update: (newConfig: ChartConfiguration<'bar'>) => void; destroy: () => void } {
	let chart = new Chart(canvas, config);

	return {
		update(newConfig: ChartConfiguration<'bar'>) {
			// Update data and options without recreating the chart
			if (newConfig.data) {
				chart.data = newConfig.data;
			}
			if (newConfig.options) {
				chart.options = newConfig.options;
			}
			chart.update('none'); // Skip animations on update for smoother experience
		},
		destroy() {
			chart.destroy();
		}
	};
}

/**
 * Generate a color palette for chart datasets
 * Uses DaisyUI-compatible colors with varying opacity
 */
export function getChartColors(count: number): { background: string[]; border: string[] } {
	// Color palette that works well in both light and dark themes
	const baseColors = [
		'59, 130, 246', // Blue
		'34, 197, 94', // Green
		'249, 115, 22', // Orange
		'168, 85, 247', // Purple
		'236, 72, 153', // Pink
		'14, 165, 233', // Sky
		'245, 158, 11', // Amber
		'99, 102, 241' // Indigo
	];

	const background: string[] = [];
	const border: string[] = [];

	for (let i = 0; i < count; i++) {
		const color = baseColors[i % baseColors.length];
		background.push(`rgba(${color}, 0.6)`);
		border.push(`rgba(${color}, 1)`);
	}

	return { background, border };
}

/**
 * Format a run label from model name and timestamp
 * Example: "gemma3:4b" + "2024-01-15T14:30:00Z" → "gemma3 14:30"
 */
export function formatRunLabel(model: string | undefined, timestamp: string): string {
	const modelName = model?.split(':')[0] || 'Unknown';
	const time = new Date(timestamp).toLocaleTimeString('en-US', {
		hour: '2-digit',
		minute: '2-digit',
		hour12: false
	});
	return `${modelName} ${time}`;
}
