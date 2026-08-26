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

async function postJson<T>(url: string, body: unknown, timeoutMs: number = DEFAULT_TIMEOUT_MS): Promise<T> {
	return sendJson<T>('POST', url, body, timeoutMs);
}

async function sendJson<T>(
	method: string,
	url: string,
	body: unknown,
	timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), timeoutMs);
	try {
		const response = await fetch(url, {
			method,
			headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
			body: body === undefined ? undefined : JSON.stringify(body),
			signal: controller.signal
		});
		if (!response.ok) {
			// FastAPI puts the useful message in `detail`; fall back to raw text.
			const text = await response.text();
			let detail = text;
			try {
				const parsed = JSON.parse(text);
				if (typeof parsed?.detail === 'string') detail = parsed.detail;
				else if (parsed?.detail) detail = JSON.stringify(parsed.detail);
			} catch {
				/* keep raw text */
			}
			throw new Error(detail || `Request failed (${response.status} ${response.statusText})`);
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

export interface TriggerEvalRunRequest {
	name?: string | null;
	tier: string;
	datasets: string[];
	samples: number;
	seed: number | null;
	judge_enabled: boolean;
	groundedness: boolean;
}

export interface JobCreatedResponse {
	job_id: string;
	status: string;
	created_at: string;
}

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
	// null = the metric was undefined for this run's data (e.g. citation metrics
	// with no gold passages). Never render it as 0.
	metrics: Record<string, number | null>;
	groups: Record<string, string[]>;
}

export interface EvalRunListResponse {
	runs: EvalRunSummary[];
	total: number;
}

export interface ScorecardMetric {
	name: string;
	/** null when the metric is undefined for the dataset — not a measured zero. */
	value: number | null;
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
	judge_model?: string | null;
	/** Set when the judge shares a provider with the generation model. */
	judge_independence_warning?: string | null;
	scoring?: {
		weights?: Record<string, number>;
		latency_threshold_ms?: number;
		max_cost_per_query_usd?: number;
	};
	cache?: { judge: boolean; query: boolean; hits: number; misses: number } | null;
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

export interface MetricSignificance {
	metric: string;
	n_paired: number;
	mean_a: number;
	mean_b: number;
	delta: number;
	ci_low: number;
	ci_high: number;
	p_value: number;
	test: 'paired_bootstrap' | 'mcnemar_exact';
	/** CI excludes zero, before multiple-comparisons correction. */
	significant: boolean;
	/** Survives Benjamini-Hochberg across the metric family. Prefer this. */
	significant_corrected: boolean | null;
	/** Below the paired-sample floor — indicative only. */
	underpowered: boolean;
	discordant_b_better: number | null;
	discordant_a_better: number | null;
}

export interface SignificanceReport {
	run_a: string;
	run_b: string;
	alpha: number;
	family_size: number;
	expected_false_positives: number;
	any_spurious_probability: number;
	underpowered_threshold: number;
	metrics: MetricSignificance[];
	/** Metrics in both runs with no per-question data to pair on. */
	skipped: string[];
}

export interface EvalCompareResponse {
	runs: EvalRunDetail[];
	deltas: Record<string, number | null>;
	/** One report per non-baseline run, each compared against runs[0]. */
	significance: SignificanceReport[];
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

// Triggering a run only queues it; the runner itself can take many minutes.
export function triggerEvalRun(req: TriggerEvalRunRequest): Promise<JobCreatedResponse> {
	return postJson<JobCreatedResponse>(`${API_BASE}/runs`, req);
}

export function cancelActiveEvalJob(): Promise<{ status: string }> {
	return sendJson<{ status: string }>('DELETE', `${API_BASE}/runs/active`, undefined);
}
