/**
 * Configuration diff utilities for comparing ConfigSnapshot objects
 */
import type { ConfigSnapshot } from '$lib/api';

export interface DiffLine {
	key: string;
	value: string;
	oldValue?: string;
	type: 'same' | 'added' | 'removed' | 'changed';
}

/**
 * Compare two ConfigSnapshot objects and return diff lines
 * Produces a git-style diff with additions, removals, and changes
 */
export function diffConfigs(
	configA: ConfigSnapshot | null | undefined,
	configB: ConfigSnapshot | null | undefined
): DiffLine[] {
	if (!configA && !configB) return [];
	if (!configA) return objectToDiff(configB!, 'added');
	if (!configB) return objectToDiff(configA, 'removed');

	const results: DiffLine[] = [];

	// Define the keys to compare in order
	const configKeys: (keyof ConfigSnapshot)[] = [
		'llm_provider',
		'llm_model',
		'llm_base_url',
		'embedding_provider',
		'embedding_model',
		'retrieval_top_k',
		'hybrid_search_enabled',
		'rrf_k',
		'contextual_retrieval_enabled',
		'reranker_enabled',
		'reranker_model',
		'reranker_top_n'
	];

	for (const key of configKeys) {
		const aVal = formatValue(configA[key]);
		const bVal = formatValue(configB[key]);

		if (aVal === '' && bVal === '') {
			// Both undefined, skip
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
function objectToDiff(config: ConfigSnapshot, type: 'added' | 'removed'): DiffLine[] {
	const configKeys: (keyof ConfigSnapshot)[] = [
		'llm_provider',
		'llm_model',
		'llm_base_url',
		'embedding_provider',
		'embedding_model',
		'retrieval_top_k',
		'hybrid_search_enabled',
		'rrf_k',
		'contextual_retrieval_enabled',
		'reranker_enabled',
		'reranker_model',
		'reranker_top_n'
	];

	const results: DiffLine[] = [];
	for (const key of configKeys) {
		const value = formatValue(config[key]);
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
		.replace(/Llm/g, 'LLM')
		.replace(/Rrf/g, 'RRF');
}

/**
 * Format a config value for display
 */
function formatValue(value: unknown): string {
	if (value === undefined || value === null) return '';
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
