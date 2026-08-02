/**
 * Configuration diff utilities for comparing eval run configs
 */
import type { EvalRunConfig } from '$lib/api/evals';

export interface DiffLine {
	key: string;
	value: string;
	oldValue?: string;
	type: 'same' | 'added' | 'removed' | 'changed';
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
// off or absent. Showing them as added/removed would report a config change that
// did not happen. `reranker_model` is deliberately excluded: there, null does
// mean "no reranker".
const UNKNOWN_WHEN_NULL = new Set<string>([
	'retrieval_top_k',
	'hybrid_search_enabled',
	'contextual_retrieval_enabled'
]);

/**
 * Compare two eval run configs and return diff lines
 * Produces a git-style diff with additions, removals, and changes
 */
export function diffConfigs(
	configA: EvalRunConfig | null | undefined,
	configB: EvalRunConfig | null | undefined
): DiffLine[] {
	if (!configA && !configB) return [];
	if (!configA) return objectToDiff(configB!, 'added');
	if (!configB) return objectToDiff(configA, 'removed');

	const results: DiffLine[] = [];

	for (const key of CONFIG_KEYS) {
		const aVal = formatValue(configA[key], key);
		const bVal = formatValue(configB[key], key);

		if (aVal === '' && bVal === '') {
			continue;
		} else if (aVal === '') {
			results.push({ key: formatKey(key), value: bVal, type: 'added' });
		} else if (bVal === '') {
			results.push({ key: formatKey(key), value: aVal, type: 'removed' });
		} else if (aVal !== bVal) {
			results.push({ key: formatKey(key), value: bVal, oldValue: aVal, type: 'changed' });
		} else {
			results.push({ key: formatKey(key), value: aVal, type: 'same' });
		}
	}

	return results;
}

/**
 * Convert a single config to diff lines (all added or all removed)
 */
function objectToDiff(config: EvalRunConfig, type: 'added' | 'removed'): DiffLine[] {
	const results: DiffLine[] = [];
	for (const key of CONFIG_KEYS) {
		const value = formatValue(config[key], key);
		if (value !== '') {
			results.push({ key: formatKey(key), value, type });
		}
	}
	return results;
}

/**
 * Format a config key for display (snake_case to Title Case)
 */
function formatKey(key: string): string {
	return key
		.replace(/_/g, ' ')
		.replace(/\b\w/g, (c) => c.toUpperCase())
		.replace(/Llm/g, 'LLM');
}

/**
 * Format a config value for display
 */
function formatValue(value: unknown, key?: string): string {
	if (value === undefined || value === null) {
		return key && UNKNOWN_WHEN_NULL.has(key) ? 'Unknown' : '';
	}
	if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
	return String(value);
}

/**
 * Get CSS classes for a diff line type
 */
export function getDiffLineClasses(type: DiffLine['type']): string {
	switch (type) {
		case 'added':
			return 'bg-success/20 text-success';
		case 'removed':
			return 'bg-error/20 text-error';
		case 'changed':
			return 'bg-warning/20 text-warning';
		default:
			return '';
	}
}

/**
 * Get the prefix character for a diff line
 */
export function getDiffPrefix(type: DiffLine['type']): string {
	switch (type) {
		case 'added':
			return '+';
		case 'removed':
			return '-';
		case 'changed':
			return '~';
		default:
			return ' ';
	}
}
