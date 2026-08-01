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

Streams responses from `POST /api/query/stream` via SSE. Renders a message list with streaming placeholders, session metadata badges (created-at, LLM model, search type), and deduplicated source badges linking to document downloads. On a stream abort, a `[Cancelled]` suffix is appended to the partial message; on stream failure, `[Error: Connection interrupted]` is appended — there is no retry button, the user must retype and resend. There is no explicit empty-state copy beyond the input's placeholder text.

### `/documents`

Fetches the full document list (`GET /api/documents`) and renders it as a sortable table with row checkboxes and bulk-select delete. There is no server-side pagination — see "Known rough edges" below.

### `/upload`

Handles duplicate-checking, multipart upload, and progress polling. Renders a per-file progress table with status badges (uploading/processing/done/error/skipped) and a dedicated alert for the case of Ollama being unreachable during embedding (a 503 from the upload endpoint).

### `/settings`

Three stacked panels: UI (tooltip toggle), RAG Pipeline (contextual retrieval toggle), and API Keys. This page exposes only two of the many system-config knobs the API already reports read-only via `/api/metrics/system` — there is no UI here for retrieval top-k, hybrid search on/off, reranker on/off, or chunk size.

### `/analytics`

A sticky header shows system name/version/health, document/chunk counts, latest-run badges, and live job progress when an eval is running (polled every 5 seconds regardless of which tab is active). Below that, three tabs share one `SystemMetrics` fetch and one eval-dashboard fetch, refreshed together every 30 seconds if auto-refresh is enabled. The active tab is driven by a `?tab=` query parameter, with legacy alias redirects for older tab ids (`overview`, `scorecard`, `trends`, `compare`) — a backward-compatibility shim implying the current three-tab layout replaced an earlier, larger one.

## Components

### Analytics subsystem (`lib/components/analytics/`)

This is the largest and, before this document, entirely undocumented part of the component tree.

- **`AnalyticsTabs`** — presentational tab bar; no data of its own.
- **`ConfigContext`** — the "config under test" chip strip. Prefers an eval run's own config fields (LLM/embedding/reranker model, top-k, hybrid search + RRF k, contextual retrieval), falling back to live system metrics when a run's config omits a field. Chunk size/overlap is system-only — there is no equivalent field on a run's config.
- **`HealthTab`** — the default landing tab. Fetches the two most recent eval runs, derives a "weakest link" verdict banner across retrieval/generation/citation/abstention metric groups, and renders stat panels for weighted score, retrieval, generation, cost per query, and latency p95, each with a delta against the previous run. Composes `ConfigContext`, `LatencyPanel`, and `MetricBreakdown`.
- **`SystemHealthTab`** ("System" tab) — renders entirely from one `SystemMetrics` object: a component-status strip, a models table (type/model/provider/params/size/status per LLM, embedding, reranker, eval model), and index-statistics tiles (document count, chunk count, retrieval top-k, final top-n). A number of descriptive/research fields the API already returns — hybrid-search description and research references, contextual-retrieval description, reranker reference URL, the overall pipeline description, and the full evaluation-metrics glossary — are fetched into the type but never rendered anywhere in this tab or elsewhere.
- **`ExperimentsTab`** — combines run-history trends and a per-run comparison table into one tab. Sparkline cards are driven by weighted score, faithfulness, answer correctness, latency p95, and average cost across up to 50 recent runs. The comparison table groups metric rows (headline → retrieval → generation → citation → abstention → cost/speed), with delta coloring against a per-metric direction-aware epsilon. It renders `RunSelector`, `ExportButton`, and `ConfigDiff`.
- **`HealthBadge`** — presentational only. Maps a health enum (`good|warn|bad|unknown`) to a color, shape, and word — deliberately never color alone. This is the one place in the app that takes that accessibility care; see "Known rough edges."
- **`LatencyPanel`** — renders p50/avg/p95 latency bars. The eval harness only times each query end-to-end, so there is no retrieval-vs-generation stage split in the underlying data — this panel is an intentional, documented degrade rather than a missing feature.
- **`MetricBreakdown`** — full per-group metric list. Generation-group rows show a `± std_dev` figure when present; retrieval, citation, and abstention metrics carry the identical field from the same backend computation, but the component only reads it for the generation group, so it is silently dropped for the other three.
- **`MetricSparkline`** — a generic `layerchart` `LineChart` wrapper over any numeric series, with a "not enough history" fallback below two data points. This is the real replacement for the never-existing `Sparkline.svelte`/`@fnando/sparkline`.
- **`StatPanel`** — presentational card: label, value, health accent, optional delta, optional badge.
- **`InfoTip`** — a fixed-position hover/focus tooltip bubble; text supplied by the caller from static copy constants.

### Other components (`lib/components/`)

- **`ChatSidebar`** — session list (active/archived), split from a single sessions fetch. Only a session's title is shown in the list row itself; created-at, updated-at, LLM model, search type, and temporary-flag are all fetched but surface only once a session is opened on the `/chat` page. Supports resizable width and collapse, both persisted via cookie-backed stores. Handles archive/unarchive/delete and a client-side `.txt` export of chat history.
- **`ConfigDiff`** — a git-style diff (added/removed/changed lines) of a fixed set of `EvalRunConfig` keys (LLM provider/model, embedding model, reranker model, retrieval top-k, hybrid search enabled, contextual retrieval enabled) between exactly two runs.
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

- **Silent settings-load failure.** If `/settings`'s fetch of settings or API-key status fails, the failure is only sent to `console.error` — there is no user-visible error state. The page just keeps showing default or stale toggle values with no indication anything went wrong.
- **Client-side row cap on the documents table, not real pagination.** `/documents` fetches the entire document list from the API (which takes no limit/offset) and then truncates the rendered table to a hardcoded maximum of 15 visible rows, with a "+N more documents stored" footer. Large corpora are still fetched in full; only the display is truncated.
- **Bulk-delete has no partial-failure handling.** Deleting multiple documents issues sequential `DELETE` calls in a loop, not a batch endpoint. If one call in the middle fails, the loop's catch sets one generic error message and skips the remaining deletes silently — leaving the selection state inconsistent with what was actually deleted on the server.
- **Simulated upload progress before task IDs exist.** Before the server hands back a real batch/task ID to poll, the upload page fakes progress with a fixed-increment timer rather than reflecting actual bytes transferred. Once a task ID exists, progress switches to real polling of the task-status endpoint.
- **Config diff only ever compares baseline A vs. run B.** Up to four runs can be selected for comparison, and the metrics table shows all of them, but the git-style config diff is rendered only for the oldest-selected run ("A") against the second-selected run ("B") — a third or fourth selected run gets metric columns but no config-diff coverage.
- **Color-only status indicators outside `HealthBadge`.** `HealthBadge` deliberately encodes health via shape and word as well as color. Everywhere else status is shown as a colored dot with no shape or text alternative — the component-status strip, the models-table status badges, and session-list indicators — so that accessibility care is isolated to one component rather than applied consistently.

Beyond these five, a few smaller issues are worth knowing about: loading affordances are inconsistent (spinners on Documents/Analytics/Chat vs. plain "Loading..." text with no spinner on Settings); destructive actions (document delete, session delete) use plain browser `confirm()` dialogs with no undo; and there is no UI path anywhere in the app to trigger or cancel an eval run — both require the CLI or a direct API call, a limitation the Experiments tab's own empty-state copy states explicitly.
