// Evals service API client — proxied at /api/eval/* by hooks.server.ts (evals service, port 8002)

const API_BASE = '/api/eval';

// Hard ceiling so a hung proxy/backend can never leave a tab spinning forever.
const DEFAULT_TIMEOUT_MS = 15000;

async function fetchJson<T>(url: string, timeoutMs: number = DEFAULT_TIMEOUT_MS): Promise<T> {
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), timeoutMs);
	try {
		const response = await fetch(url, { signal: controller.signal });
		if (!response.ok) {
			throw new Error(`Request failed (${response.status} ${response.statusText}): ${url}`);
		}
		return (await response.json()) as T;
	} catch (e) {
		if (e instanceof DOMException && e.name === 'AbortError') {
			throw new Error(`Request timed out after ${timeoutMs / 1000}s: ${url}`);
		}
		throw e;
	} finally {
		clearTimeout(timer);
	}
}

// ============================================================================
// Types — mirror services/evals/api/schemas.py
// ============================================================================

export interface ProgressInfo {
	current_question: number;
	total_questions: number;
	current_dataset: string;
	phase: string;
	elapsed_seconds: number;
}

export interface ActiveEvalJob {
	job_id: string;
	status: string;
	progress: ProgressInfo;
}

export interface EvalDashboardMetrics {
	retrieval_relevance: number | null;
	faithfulness: number | null;
	answer_completeness: number | null;
	answer_relevance: number | null;
	latency_p50_seconds: number | null;
	latency_p95_seconds: number | null;
	latency_avg_seconds: number | null;
	avg_cost_usd: number | null;
	total_cost_usd: number | null;
	total_prompt_tokens: number | null;
	total_completion_tokens: number | null;
	cost_model: string | null;
}

export interface EvalRunSummary {
	id: string;
	name: string;
	created_at: string;
	completed_at: string | null;
	tier: string;
	datasets: string[];
	question_count: number;
	error_count: number;
	duration_seconds: number | null;
	weighted_score: number | null;
	llm_model: string | null;
	dashboard_metrics: EvalDashboardMetrics | null;
	metrics: Record<string, number>;
	groups: Record<string, string[]>;
}

export interface EvalRunListResponse {
	runs: EvalRunSummary[];
	total: number;
}

export interface ScorecardMetric {
	name: string;
	value: number;
	group: string;
	sample_size?: number;
	details?: Record<string, unknown>;
}

export interface Scorecard {
	metrics: ScorecardMetric[];
	by_group: Record<string, string[]>;
}

export interface WeightedScoreDetail {
	score: number;
	weights: Record<string, number>;
	contributions: Record<string, number>;
	objectives: Record<string, number>;
}

export interface EvalRunConfig {
	llm_model?: string;
	llm_provider?: string;
	embedding_model?: string;
	reranker_model?: string;
	retrieval_top_k?: number;
	hybrid_search_enabled?: boolean;
	contextual_retrieval_enabled?: boolean;
}

export interface EvalRunMetadata {
	samples_per_dataset?: number;
	seed?: number | null;
	tier?: string;
}

export interface EvalRunDetail {
	id: string;
	name: string;
	created_at: string;
	completed_at: string | null;
	tier: string;
	datasets: string[];
	config: EvalRunConfig;
	scorecard: Scorecard | null;
	weighted_score: WeightedScoreDetail | null;
	question_count: number;
	error_count: number;
	duration_seconds: number | null;
	metadata: EvalRunMetadata;
	dashboard_metrics: EvalDashboardMetrics | null;
}

export interface EvalCompareResponse {
	runs: EvalRunDetail[];
	deltas: Record<string, number | null>;
}

export interface EvalDatasetInfo {
	name: string;
	description: string;
	source_url: string;
	supported_tiers: string[];
}

export interface EvalDashboardResponse {
	latest_run: EvalRunSummary | null;
	total_runs: number;
	active_job: ActiveEvalJob | null;
}

// ============================================================================
// Fetchers
// ============================================================================

export function fetchEvalDashboard(): Promise<EvalDashboardResponse> {
	return fetchJson<EvalDashboardResponse>(`${API_BASE}/dashboard`);
}

export function fetchEvalRuns(limit: number = 50): Promise<EvalRunListResponse> {
	const params = new URLSearchParams();
	params.set('limit', limit.toString());
	return fetchJson<EvalRunListResponse>(`${API_BASE}/runs?${params}`);
}

export function fetchEvalRun(id: string): Promise<EvalRunDetail> {
	return fetchJson<EvalRunDetail>(`${API_BASE}/runs/${id}`);
}

export function compareEvalRuns(ids: string[]): Promise<EvalCompareResponse> {
	const params = new URLSearchParams();
	params.set('ids', ids.join(','));
	return fetchJson<EvalCompareResponse>(`${API_BASE}/runs/compare?${params}`);
}

export function fetchActiveEvalJob(): Promise<ActiveEvalJob | null> {
	return fetchJson<ActiveEvalJob | null>(`${API_BASE}/runs/active`);
}

export function fetchEvalDatasets(): Promise<EvalDatasetInfo[]> {
	return fetchJson<EvalDatasetInfo[]>(`${API_BASE}/datasets`);
}
