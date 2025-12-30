/**
 * Export utilities for evaluation data
 * Client-side CSV and JSON generation
 */
import type { EvaluationRun, GoldenBaseline } from '$lib/api';

export interface ExportData {
	runs: EvaluationRun[];
	baseline: GoldenBaseline | null;
	exportedAt: string;
}

/**
 * Export evaluation runs to CSV format
 */
export function exportToCSV(runs: EvaluationRun[]): void {
	if (runs.length === 0) {
		console.warn('No runs to export');
		return;
	}

	// Get all unique metric names across all runs
	const allMetrics = new Set<string>();
	for (const run of runs) {
		for (const metric of Object.keys(run.metric_averages)) {
			allMetrics.add(metric);
		}
	}
	const metrics = Array.from(allMetrics).sort();

	// Build CSV headers
	const headers = [
		'run_id',
		'timestamp',
		'model',
		'provider',
		'framework',
		'eval_model',
		'total_tests',
		'passed_tests',
		'pass_rate',
		'avg_latency_ms',
		'p95_latency_ms',
		'cost_per_query_usd',
		...metrics.map((m) => `metric_${m}`),
		...metrics.map((m) => `pass_rate_${m}`)
	];

	// Build CSV rows
	const rows = runs.map((run) => {
		const values = [
			run.run_id,
			run.timestamp,
			run.config_snapshot?.llm_model || '',
			run.config_snapshot?.llm_provider || '',
			run.framework,
			run.eval_model,
			run.total_tests.toString(),
			run.passed_tests.toString(),
			(run.pass_rate * 100).toFixed(1),
			run.latency?.avg_query_time_ms?.toFixed(0) || '',
			run.latency?.p95_query_time_ms?.toFixed(0) || '',
			run.cost?.cost_per_query_usd?.toFixed(4) || '',
			...metrics.map((m) => ((run.metric_averages[m] ?? 0) * 100).toFixed(1)),
			...metrics.map((m) => ((run.metric_pass_rates[m] ?? 0) * 100).toFixed(1))
		];
		return values.map(escapeCSV).join(',');
	});

	const csv = [headers.join(','), ...rows].join('\n');
	downloadFile(csv, generateFilename('csv'), 'text/csv');
}

/**
 * Export evaluation data to JSON format
 */
export function exportToJSON(data: ExportData): void {
	const json = JSON.stringify(data, null, 2);
	downloadFile(json, generateFilename('json'), 'application/json');
}

/**
 * Escape a value for CSV (handle commas, quotes, newlines)
 */
function escapeCSV(value: string): string {
	if (value.includes(',') || value.includes('"') || value.includes('\n')) {
		return `"${value.replace(/"/g, '""')}"`;
	}
	return value;
}

/**
 * Generate a filename with timestamp
 */
function generateFilename(extension: string): string {
	const date = new Date().toISOString().slice(0, 10);
	const time = new Date().toISOString().slice(11, 16).replace(':', '');
	return `eval-comparison-${date}-${time}.${extension}`;
}

/**
 * Trigger a file download in the browser
 */
function downloadFile(content: string, filename: string, mimeType: string): void {
	const blob = new Blob([content], { type: mimeType });
	const url = URL.createObjectURL(blob);

	const link = document.createElement('a');
	link.href = url;
	link.download = filename;
	link.style.display = 'none';

	document.body.appendChild(link);
	link.click();

	document.body.removeChild(link);
	URL.revokeObjectURL(url);
}
