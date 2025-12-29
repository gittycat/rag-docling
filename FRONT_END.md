# Frontend Development Guide

Technical documentation for the SvelteKit webapp. Focuses on UI architecture, components, state management, theming, and client-side patterns.

## Table of Contents

- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Routing & Pages](#routing--pages)
- [Components](#components)
- [State Management](#state-management)
- [API Client](#api-client)
- [Theming](#theming)
- [Server-Side Rendering](#server-side-rendering)
- [Build & Deployment](#build--deployment)
- [Development Workflow](#development-workflow)

## Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| SvelteKit | 2.49+ | Full-stack framework with SSR |
| Svelte | 5.45+ | Component framework (Runes API) |
| TypeScript | 5.9+ | Type safety |
| Tailwind CSS | 4.1+ | Utility-first styling |
| DaisyUI | 5.5+ | Component library with theming |
| Vite | 7.2+ | Build tool and dev server |
| Node Adapter | 5.2+ | Production deployment |

### Key Libraries

- **@fnando/sparkline**: Inline SVG trend charts for metrics dashboard
- **@sveltejs/adapter-node**: Server deployment adapter

## Project Structure

```
services/webapp/
├── src/
│   ├── app.css                 # Global styles + DaisyUI theme config
│   ├── app.d.ts                # Global TypeScript definitions
│   ├── hooks.server.ts         # Server middleware (API proxy, theme SSR)
│   ├── lib/
│   │   ├── api.ts              # RAG server API client
│   │   ├── themes.ts           # Theme configuration
│   │   ├── components/         # Reusable UI components
│   │   ├── stores/             # Svelte stores for state
│   │   └── utils/              # Helper utilities
│   └── routes/                 # File-based routing
├── static/                     # Static assets (logo, robots.txt)
├── package.json
├── svelte.config.js
├── vite.config.ts
└── Dockerfile
```

## Routing & Pages

SvelteKit uses file-based routing. Each page serves a specific function:

| Route | File | Purpose |
|-------|------|---------|
| `/` | `+page.svelte` | Redirects to `/chat` |
| `/chat` | `chat/+page.svelte` | RAG query interface with streaming |
| `/documents` | `documents/+page.svelte` | Document inventory management |
| `/upload` | `upload/+page.svelte` | File upload with progress tracking |
| `/dashboard` | `dashboard/+page.svelte` | System metrics and evaluation |
| `/settings` | `settings/+page.svelte` | User preferences |

### Chat Page Features

- Real-time streaming responses via Server-Sent Events (SSE)
- Session-based conversation memory
- Source document display with excerpts
- Stop streaming capability via AbortController
- Auto-scroll on new messages
- Session title generation via LLM

### Documents Page Features

- Sortable table (by name, chunks, upload date)
- Multi-select for bulk deletion
- Relative time formatting for upload dates
- Row limit with overflow indicator

### Upload Page Features

- Dual trigger: file picker and directory picker
- SHA-256 hash computation for duplicate detection
- Pre-upload duplicate check via backend API
- Real-time progress tracking with polling
- Status badges: uploading, processing, done, error, skipped

### Dashboard Features

- System overview: models, retrieval config, health status
- Evaluation metrics with sparkline trends
- Color-coded pass/fail thresholds
- Auto-refresh toggle (30-second interval)

## Components

### ChatSidebar (`lib/components/ChatSidebar.svelte`)

Primary navigation and session management component.

**Features:**
- Resizable width (draggable edge)
- Collapsible mode (icons only)
- Session sections: Active and Archived
- Per-session actions: archive, delete, export
- Current session highlighting
- Theme toggle in footer

**State Persistence (cookies):**
- `sidebarOpen`: Expanded vs collapsed
- `sidebarWidth`: Width in pixels (100-333px)
- `sidebarRecentExpanded`: Recent sessions section visibility
- `sidebarArchivedExpanded`: Archived sessions section visibility

### ThemeToggle (`lib/components/ThemeToggle.svelte`)

Light/dark theme switcher using DaisyUI swap component.

**Themes:**
- Nord (light) - Default
- Dim (dark) - Prefers dark mode

**Persistence:**
- LocalStorage: Immediate client access
- Cookie: SSR access for FOUC prevention

### Sparkline (`lib/components/Sparkline.svelte`)

Inline SVG trend visualization using @fnando/sparkline.

**Props:**
- `values`: Number array for data points
- `width`, `height`: Dimensions (default: 60x16)
- `strokeColor`, `fillColor`: Styling

**Usage:** Dashboard metric trends (evaluation scores over time)

### Root Layout (`routes/+layout.svelte`)

Global page wrapper providing consistent navigation.

**Structure:**
- ChatSidebar (always visible)
- Main content area with conditional header
- Page-specific header buttons (upload triggers on Documents page)
- Tooltip visibility class control

## State Management

Uses Svelte 5 runes (`$state`, `$derived`, `$effect`) within components and writable stores for cross-component communication.

### Stores (`lib/stores/`)

| Store | File | Purpose |
|-------|------|---------|
| `exportChatFn` | `chat.ts` | Chat export callback reference |
| `canExportChat` | `chat.ts` | Export availability flag |
| `sidebarOpen` | `sidebar.ts` | Collapsed state |
| `sidebarWidth` | `sidebar.ts` | Width in pixels |
| `showRecentExpanded` | `sidebar.ts` | Recent section visibility |
| `showArchivedExpanded` | `sidebar.ts` | Archived section visibility |
| `sessionRefreshTrigger` | `sidebar.ts` | Counter to trigger session reload |
| `showTooltips` | `ui.ts` | Global tooltip visibility |

### State Persistence Strategy

All persistent UI state uses cookies with 1-year expiry:
- Server-side readable (SSR compatibility)
- Client-side updates via store subscriptions
- Utility: `lib/utils/cookies.ts`

### Session State Flow

1. User navigates to `/chat` or `/chat?session_id=xxx`
2. If no session_id, starts in "new chat" mode
3. First message creates session via API
4. Session ID updates URL without navigation
5. `sessionRefreshTrigger` incremented to update sidebar

## API Client

Centralized API access in `lib/api.ts` (~650 lines).

### Base Configuration

- **Base URL**: `/api` (proxied to RAG server)
- **Content Type**: `application/json` for most endpoints
- **Streaming**: Native fetch with ReadableStream for SSE

### Endpoint Categories

**Documents:**
- `fetchDocuments(sortBy, sortOrder)` - List with sorting
- `deleteDocument(documentId)` - Delete single document
- `checkDuplicateFiles(files)` - Pre-upload duplicate check

**Upload:**
- `uploadFiles(files)` - POST multipart form data
- `fetchBatchProgress(batchId)` - Poll upload status
- `computeFileHash(file)` - SHA-256 via Web Crypto API

**Query:**
- `streamQuery(query, sessionId, isTemporary, signal)` - SSE generator
- `sendQuery(query, sessionId)` - Non-streaming fallback
- `getChatHistory(sessionId)` - Full conversation retrieval
- `clearChatSession(sessionId)` - Delete session history

**Sessions:**
- `fetchChatSessions(includeArchived)` - List sessions
- `createNewSession(firstMessage?)` - Create with optional title
- `deleteSession(sessionId)` - Remove session
- `archiveSession(sessionId)` / `unarchiveSession(sessionId)` - Toggle archive

**Metrics:**
- `fetchSystemMetrics()` - System overview
- `fetchHealth()` - Health check
- `fetchEvaluationSummary()` - Evaluation results

### Type Definitions

All API responses have TypeScript interfaces matching backend Pydantic models:
- `Document`, `DocumentListResponse`
- `ChatMessage`, `ChatSource`, `QueryResponse`
- `SessionMetadata`, `CreateSessionResponse`
- `SystemMetrics`, `EvaluationSummary`

## Theming

### Theme Configuration

DaisyUI themes configured in `app.css`:

```
Themes: nord (light, default), dim (dark, prefers-dark)
```

### Custom CSS Classes

| Class | Purpose |
|-------|---------|
| `.btn-action` | Outlined ghost button for icon actions |
| `.tooltips-hidden .tooltip` | Hides all DaisyUI tooltips |

### DaisyUI Components Used

- **Layout**: drawer, sidebar patterns
- **Navigation**: menu, menu-item
- **Forms**: input, join (grouped inputs)
- **Buttons**: btn, btn-ghost, btn-square, btn-sm
- **Feedback**: alert, badge, loading, tooltip
- **Display**: table, chat-bubble
- **Controls**: swap (theme toggle), checkbox

### Tailwind Utilities

Primary utilities for layout and spacing:
- Flexbox: `flex`, `gap-X`, `justify-between`, `items-center`
- Typography: `text-sm`, `text-lg`, `font-semibold`
- Colors: `text-base-content`, `text-error`, `bg-base-200`
- Responsive: `md:block`, `lg:hidden`

## Server-Side Rendering

### hooks.server.ts Responsibilities

1. **API Proxy** (production mode)
   - Path: `/api/*` → `RAG_SERVER_URL`
   - Strips `/api` prefix
   - Forwards all headers except `host`
   - Supports streaming request/response bodies

2. **Theme SSR Injection**
   - Reads `theme` cookie from request
   - Injects `data-theme` attribute into HTML response
   - Prevents flash of unstyled content (FOUC)

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RAG_SERVER_URL` | `http://localhost:8001` | Backend API URL |
| `ORIGIN` | - | SvelteKit origin for CORS |
| `MAX_UPLOAD_SIZE` | `80` | Max file upload size (MB) |

## Build & Deployment

### Build Command

```bash
npm run build
```

Produces:
- `build/client/` - Static assets
- `build/server/` - Node.js server

### Dockerfile

Multi-stage build:
1. **Build stage**: Node 22, npm install, vite build
2. **Run stage**: Node 22-alpine, copy build output, run server

**Container config:**
- User: `sveltekit:1001` (non-root)
- Port: 3000 (mapped to 8000 in docker-compose)
- Workdir: `/app`

### Production Proxy

In production, the webapp container proxies `/api/*` to `rag-server:8001` via the hooks.server.ts logic.

## Development Workflow

### Commands

| Command | Purpose |
|---------|---------|
| `npm run dev` | Start dev server with HMR |
| `npm run build` | Production build |
| `npm run preview` | Preview production build |
| `npm run check` | TypeScript and Svelte checks |
| `npm run check:watch` | Continuous type checking |

### Dev Server Configuration

- URL: `http://localhost:5173`
- Host binding: `0.0.0.0` (accessible from Docker)
- API Proxy: `/api/*` → `http://localhost:8001`
- Hot Module Replacement: Enabled

### Svelte 5 Patterns

Uses Svelte 5 runes for reactivity:
- `$state(initial)` - Reactive state declaration
- `$derived(expr)` - Computed values
- `$effect(() => ...)` - Side effects
- `$props()` - Component props

### Browser APIs Used

- **Fetch API**: All HTTP requests
- **Web Crypto API**: SHA-256 file hashing
- **LocalStorage**: Theme persistence
- **AbortController**: Request cancellation
- **ReadableStream**: SSE parsing

## Svelte MCP Server

For Svelte-related coding, use the Svelte MCP server which provides:
- Official Svelte 5 documentation
- SvelteKit documentation
- Code validation and autofixing
- Playground link generation

See CLAUDE.md for MCP configuration details.
