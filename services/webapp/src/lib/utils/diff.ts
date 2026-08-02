/**
 * Configuration diff utilities for comparing eval run configs.
 *
 * n-way by design: the comparison UI lets a user select up to four runs, so a
 * two-column diff would silently ignore selected input.
 */
import type { EvalRunConfig } from '$lib/api/evals';

export interface DiffCell {
	value: string;
	/** Differs from the baseline (first) column. */
	changed: boolean;
	/** Value was never captured for this run — not the same as "off"/"absent". */
	unknown: boolean;
}

export interface DiffRow {
	key: string;
	cells: DiffCell[];
	/** At least one column differs from the baseline. */
	varies: boolean;
}

const CONFIG_KEYS: (keyof EvalRunConfig)[] = [
	'llm_provider',
	'llm_model',
	'embedding_model',
	'reranker_model',
	'retrieval_top_k',
	'hybrid_search_enabled',
	'contextual_retrieval_enabled'
];

// For these, null means the runner never captured the setting — not that it was
// off or absent. Reporting them as changed would report a config change that did
// not happen. `reranker_model` is deliberately excluded: there, null does mean
// "no reranker".
const UNKNOWN_WHEN_NULL = new Set<string>([
	'retrieval_top_k',
	'hybrid_search_enabled',
	'contextual_retrieval_enabled'
]);

const UNKNOWN = 'Unknown';
const ABSENT = '—';

/**
 * Compare n eval run configs against the first (baseline) one.
 * Rows with no captured value in any run are omitted entirely.
 */
export function diffConfigs(configs: (EvalRunConfig | null | undefined)[]): DiffRow[] {
	if (configs.length === 0) return [];

	const rows: DiffRow[] = [];

	for (const key of CONFIG_KEYS) {
		const raw = configs.map((c) => formatValue(c?.[key], key));
		if (raw.every((v) => v === '')) continue;

		const cells: DiffCell[] = raw.map((value, i) => ({
			value: value === '' ? ABSENT : value,
			// An uncaptured value cannot be claimed to differ from anything.
			changed: i > 0 && value !== raw[0] && value !== UNKNOWN && raw[0] !== UNKNOWN,
			unknown: value === UNKNOWN
		}));

		rows.push({ key: formatKey(key), cells, varies: cells.some((c) => c.changed) });
	}

	return rows;
}

/** snake_case config key to Title Case label. */
function formatKey(key: string): string {
	return key
		.replace(/_/g, ' ')
		.replace(/\b\w/g, (c) => c.toUpperCase())
		.replace(/Llm/g, 'LLM');
}

function formatValue(value: unknown, key?: string): string {
	if (value === undefined || value === null) {
		return key && UNKNOWN_WHEN_NULL.has(key) ? UNKNOWN : '';
	}
	if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
	return String(value);
}

/** CSS classes for a cell, given whether it differs from the baseline. */
export function getDiffCellClasses(cell: DiffCell): string {
	if (cell.unknown) return 'text-base-content/40 italic';
	if (cell.changed) return 'bg-warning/20 text-warning';
	return '';
}
