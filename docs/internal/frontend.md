# Frontend

The webapp is a SvelteKit application: SvelteKit `^2.49.1`, Svelte `^5.45.6` (runes API — `$state`/`$derived`/`$props`/`$effect` are used throughout, no legacy `export let`/reactive-statement style), Vite `^7.2.6`, Tailwind CSS 4 (`@tailwindcss/vite`), DaisyUI `^5.5.14`, and `layerchart ^2.0.1` for charts. It talks to two backend services — rag-server (port 8001) and the eval service (port 8002) — through a single same-origin `/api` prefix, never directly.

The prior version of this document described a `@fnando/sparkline` dependency, a `/dashboard` route, and a `Sparkline.svelte` component. None of these exist in the codebase — verified directly against `services/webapp/package.json` (the only chart dependency is `layerchart`) and the `src/routes` / `src/lib/components` directory listing. The real analytics route is `/analytics`, backed by `AnalyticsTabs`, `HealthTab`, `SystemHealthTab`, `ExperimentsTab` and friends, and the sparkline component is `MetricSparkline.svelte`, a thin wrapper around a `layerchart` `LineChart`.

## App structure and adapter

SvelteKit uses file-based routing under `src/routes/`. All routes are flat — there are no dynamic `[param]` segments anywhere in the app; anything that looks like a resource ID (a session, a run, a document) is passed as a query string (`?session_id=...`) or built into a URL client-side, not as a route parameter.

The app is built with `@sveltejs/adapter-node` — a standalone Node server, not a static export and not an edge/serverless adapter. The production Docker image is a two-stage build: a build stage that runs `vite build`, and a run stage (Node 22-alpine, non-root user) that runs the built Node server, listening on port 3000 (mapped to host port 8000 by the base compose file).

A single global layout (`+layout.svelte`) renders the `ChatSidebar` on every route, plus a header bar with a page-title switch for non-chat routes. Upload-trigger icon buttons in that header appear only on `/documents`, and a hardcoded "back to Documents" arrow appears only on `/upload`. Per-route branching in the layout is limited to three derived booleans (`isChatPage`, `isUploadPage`, `isDocumentsPage`) — there is no generic breadcrumb or per-route slot mechanism.

### Server-side proxy (`hooks.server.ts`)

The browser never talks to a backend origin directly. `src/lib/api.ts` hardcodes its base URL to `/api` (rag-server) and `src/lib/api/evals.ts` hardcodes `/api/eval` (the eval service); every request from the browser is same-origin, and `hooks.server.ts` is the reverse proxy that resolves those prefixes server-side:

- `/api/eval/*` is forwarded to `EVALS_SERVICE_URL` (default `http://localhost:8002`), with the `/api` prefix stripped.
- every other `/api/*` path is forwarded to `RAG_SERVER_URL` (default `http://localhost:8001`), with an `Authorization: Bearer <token>` header injected server-side.

This means auth lives entirely between the SvelteKit Node process and rag-server — the browser itself never holds or sends a token. The token is read from a Docker secret file (`RAG_SERVER_AUTH_TOKEN_FILE`) or, as a fallback, a plain `RAG_SERVER_AUTH_TOKEN` env var. rag-server enforces a bearer-token check on every router except `/health`. The eval-service proxy path forwards no auth token at all — the eval service has no auth dependency of its own, so it is reachable unauthenticated end-to-end regardless of the rag-server auth posture.

`hooks.server.ts` also handles theme injection: it reads the `theme` cookie and rewrites the `data-theme` attribute in the HTML shell before sending it, to avoid a flash of unstyled theme on the initial SSR render. This only covers the cookie; a user whose only theme signal is `localStorage` (no cookie set yet) still gets one FOUC-prone load until the cookie is written.

Client-side fetches to the eval service each carry a 15-second `AbortController` timeout with a friendly error message. Fetches to rag-server (documents, upload, query, sessions) have no client-side timeout at all — a hung rag-server call simply spins the loading state indefinitely.

## Routes

| Route | Purpose |
|---|---|
| `/` | No content of its own — `onMount` redirects to `/chat`, showing a spinner in the interim. |
| `/chat` | The primary RAG chat UI; also the app's effective home route. |
| `/documents` | List and manage indexed documents. |
| `/upload` | Upload files or directories and watch per-file ingestion progress. |
| `/settings` | Toggle UI tooltips and contextual retrieval; manage provider API keys. |
| `/analytics` | System status and eval dashboard, in three tabs: Health, Experiments, System. |

### `/chat`

Streams responses from `POST /api/query/stream` via SSE. Renders a message list with streaming placeholders, session metadata badges (created-at, LLM model, search type), and an expandable source list per answer: each entry shows the document name, the retrieval score, a download link, and — when expanded — the source path and the full retrieved passage. Deduplication is per passage, not per document, so two chunks from the same file both appear. On a stream abort, a `[Cancelled]` suffix is appended to the partial message; on stream failure, `[Error: Connection interrupted]` is appended — there is no retry button, the user must retype and resend. There is no explicit empty-state copy beyond the input's placeholder text.

### `/documents`

Fetches the full document list (`GET /api/documents`) and renders it as a sortable table with row checkboxes and bulk-select delete, paged client-side (15/25/50/100 rows). The API still takes no `limit`/`offset`, so the whole list is fetched on every load — paging is display-only. Bulk delete settles every request independently and names the ones that failed.

### `/upload`

Handles duplicate-checking, multipart upload, and progress polling. Renders a per-file progress table with status badges (hashing/uploading/processing/done/error/skipped) and a dedicated alert for the case of Ollama being unreachable during embedding (a 503 from the upload endpoint). Progress is indeterminate until the task-status endpoint reports chunk counts — nothing is simulated. Files above `max_upload_size_mb` (from `GET /api/config`) are rejected before hashing.

### `/settings`

Three stacked panels: UI (tooltip toggle), RAG Pipeline (contextual retrieval toggle), and API Keys. Load failures render a per-panel error with a retry; a failed toggle update reverts the checkbox and says the change was not saved. This page exposes only two of the many system-config knobs the API already reports read-only via `/api/metrics/system` — there is no UI here for retrieval top-k, hybrid search on/off, reranker on/off, or chunk size.

### `/analytics`

A sticky header shows system name/version/health, document/chunk counts, latest-run badges, and live job progress when an eval is running (polled every 5 seconds regardless of which tab is active). Below that, three tabs share one `SystemMetrics` fetch and one eval-dashboard fetch, refreshed together every 30 seconds if auto-refresh is enabled. The active tab is driven by a `?tab=` query parameter, with legacy alias redirects for older tab ids (`overview`, `scorecard`, `trends`, `compare`) — a backward-compatibility shim implying the current three-tab layout replaced an earlier, larger one.

## Components

### Analytics subsystem (`lib/components/analytics/`)

This is the largest and, before this document, entirely undocumented part of the component tree.

- **`AnalyticsTabs`** — presentational tab bar; no data of its own.
- **`ConfigContext`** — the "config under test" chip strip. Prefers an eval run's own config fields (LLM/embedding/reranker model, top-k, hybrid search + RRF k, contextual retrieval), falling back to live system metrics when a run's config omits a field. Chunk size/overlap is system-only — there is no equivalent field on a run's config. Also shows the current LLM's per-1M-token cost rates from `GET /api/models/info`, suppressed when the run used a different LLM than the one configured now.
- **`HealthTab`** — the default landing tab. Fetches the two most recent eval runs, derives a "weakest link" verdict banner across retrieval/generation/citation/abstention metric groups, and renders stat panels for weighted score, retrieval, generation, cost per query, and latency p95, each with a delta against the previous run. Composes `WeightedScoreBreakdown`, `ConfigContext`, `LatencyPanel`, and `MetricBreakdown`.
- **`SystemHealthTab`** ("System" tab) — renders entirely from one `SystemMetrics` object: a component-status strip, a models table (type/model/provider/params/size/status per LLM, embedding, reranker, eval model), and index-statistics tiles (document count, chunk count, retrieval top-k, final top-n). A number of descriptive/research fields the API already returns — hybrid-search description and research references, contextual-retrieval description, reranker reference URL, the overall pipeline description, and the full evaluation-metrics glossary — are fetched into the type but never rendered anywhere in this tab or elsewhere.
- **`ExperimentsTab`** — combines run-history trends and a per-run comparison table into one tab. Sparkline cards are driven by weighted score, faithfulness, answer correctness, latency p95, and average cost across up to 50 recent runs. The comparison table groups metric rows (headline → retrieval → generation → citation → abstention → cost/speed), with delta coloring against a per-metric direction-aware epsilon. It renders `RunEvalPanel`, `RunSelector`, `ExportButton`, and `ConfigDiff`.
- **`HealthBadge`** — presentational only. Maps a health enum (`good|warn|bad|unknown`) to a color, shape, and word — deliberately never color alone. `showWord={false}` keeps the shape and drops the word (the label stays on `aria-label`), which is how the component-status strips and metric pills reuse it.
- **`LatencyPanel`** — renders p50/avg/p95 latency bars. The eval harness only times each query end-to-end, so there is no retrieval-vs-generation stage split in the underlying data — this panel is an intentional, documented degrade rather than a missing feature.
- **`MetricBreakdown`** — full per-group metric list. Every group shows `± std_dev` and the metric's sample size when present, and any metric carrying `details.individual_scores` gets a toggle that expands a `ScoreDistribution` histogram. Values are pilled with a threshold band rendered as shape plus color.
- **`ScoreDistribution`** — inline SVG-free histogram (flex-sized bars) of per-question scores, with n/min/p25/median/p75/max underneath. Ten bins over 0–1, last bin closed so a perfect 1.0 is counted.
- **`WeightedScoreBreakdown`** — the objectives behind the headline number: configured weight, effective share after redistribution of objectives with no data, objective score, contribution, and share of the total. Lists the objectives that were weighted but produced no data.
- **`RunEvalPanel`** — the only writer in the analytics tree. `POST /eval/runs` from a form (name, tier, datasets filtered by `supported_tiers`, samples, seed, judge toggle), a 3-second poll of `GET /eval/runs/active` for live progress, and `DELETE /eval/runs/active` to cancel. Calls back to `ExperimentsTab` to reload the run list when a job leaves the active state.
- **`MetricSparkline`** — a generic `layerchart` `LineChart` wrapper over any numeric series, with a "not enough history" fallback below two data points. This is the real replacement for the never-existing `Sparkline.svelte`/`@fnando/sparkline`.
- **`StatPanel`** — presentational card: label, value, health accent, optional delta, optional badge.
- **`InfoTip`** — a fixed-position hover/focus tooltip bubble; text supplied by the caller from static copy constants.

### Other components (`lib/components/`)

- **`ChatSidebar`** — session list (active/archived), split from a single sessions fetch. Only a session's title is shown in the list row itself; created-at, updated-at, LLM model, search type, and temporary-flag are all fetched but surface only once a session is opened on the `/chat` page. Supports resizable width and collapse, both persisted via cookie-backed stores. Handles archive/unarchive/delete and a client-side `.txt` export of chat history.
- **`ConfigDiff`** — an n-way table over a fixed set of `EvalRunConfig` keys (LLM provider/model, embedding model, reranker model, retrieval top-k, hybrid search enabled, contextual retrieval enabled): one column per selected run, baseline first, cells differing from the baseline marked. Keys the runner never captured render as `Unknown` and are never counted as a change.
- **`ExportButton`** — exports the currently selected runs to CSV (a flattened column set, including a union of all metric names across the exported runs) or to JSON (a verbatim dump of the full run objects — the one export path where fields never shown on screen, like per-token costs, do reach the user).
- **`RunSelector`** — checkbox list of up to four selectable runs, each showing name, LLM model, date, a score badge, and an error-count badge if nonzero. Dataset list, tier, question count, and duration are fetched as part of each run summary but not shown in this picker.
- **`ThemeToggle`** — sun/moon swap checkbox bound to `data-theme`; pure client theme state.

## Stores and theming

Stores live under `src/lib/stores/`:

- **`chat.ts`** — `exportChatFn` and `canExportChat`, a cross-component bridge so the sidebar's export button can call into whichever chat page instance is currently mounted.
- **`sidebar.ts`** — `sidebarOpen`, `sidebarWidth`, `showRecentExpanded`, `showArchivedExpanded`, and `sessionRefreshTrigger` (a counter incremented to force a session-list reload). All persisted to cookies.
- **`ui.ts`** — `showTooltips`, persisted to a cookie, toggled from Settings and consumed by the layout (a `tooltips-hidden` class that hides all DaisyUI tooltips) and every `InfoTip`.

Theming is DaisyUI-only, with exactly two themes: `nord` (light, default) and `dim` (dark). `ThemeToggle` flips `data-theme` on `<html>` and writes both `localStorage` and a `theme` cookie; `hooks.server.ts` reads that cookie to set `data-theme` on the server-rendered HTML shell, avoiding a flash of unstyled theme on most loads (see the caveat above for the one case it doesn't cover).

## Data-fetching pattern

There are no SvelteKit `load()` functions anywhere in the app — no `+page.ts`, `+layout.ts`, or server-side load equivalents exist for any route. Every route fetches its data client-side, from `onMount` or an `$effect`, after the page has already mounted. The direct consequence is that every navigation — including the very first page load — shows a loading state before any real content appears; there is no SSR-fetched data anywhere, so first paint is always a spinner or equivalent placeholder, never the final content.

## Known rough edges

- **No client-side timeout on rag-server calls.** Eval-service fetches carry a 15-second `AbortController` timeout; documents, upload, query, and session calls have none, so a hung backend spins the loading state indefinitely.
- **Documents paging is display-only.** `GET /api/documents` still takes no `limit`/`offset`, so the entire list is fetched on every load and paged in the browser. Real server-side pagination needs an API change.
- **No `load()` functions anywhere.** Every route fetches client-side after mount, so first paint is always a placeholder.
- **Destructive actions use browser `confirm()`** with no undo (document delete, session delete).
- **Inconsistent loading affordances** — spinners on Documents/Analytics/Chat, plain "Loading..." text on Settings.
- **Session-list indicators are still color-only.** The analytics status strips and metric pills now carry shape via `HealthBadge`; `ChatSidebar` has not been through the same pass.
- **Descriptive API fields are still unrendered** — hybrid-search and contextual-retrieval research references, reranker reference URL, `pipeline_description`, and the `evaluation_metrics` glossary are all fetched into types and never drawn.
- **`/settings` is still the one non-runes component**, using `on:` directives and plain `let` rather than `$state`.

Section 1 of [`docs/suggestions.md`](../suggestions.md) — silent settings failures, the 15-row documents cap, unhandled bulk-delete failures, simulated upload progress, the two-run config diff, color-only status, dead client code, and the missing eval trigger — was cleared on 2026-08-02; the entries there record what each fix does.
