# UI Upgrade Plan - RAG System

## Summary

Complete UI overhaul: collapsible sidebar navigation, consistent dark/light theming with browser preference detection, inline citations, stats dashboard, and toast notifications. Target: professional domain experts with compact, information-dense interface.

## User Preferences
- **Landing page:** Documents (document management first)
- **Navigation:** Collapsible sidebar (icons-only when collapsed)
- **Density:** Compact (power user focused)
- **Citations:** Inline with numbered references + expandable details
- **Theme:** Dark/light with browser preference detection (`prefers-color-scheme`)

---

## Current State

### Tech Stack
- **Framework:** SvelteKit 2 + Svelte 5
- **Styling:** Tailwind CSS 4 (minimal config)
- **State:** Svelte stores (chat, documents, theme)

### Current Issues
1. Theme store hardcoded to 'dark', no browser preference detection
2. Only ChatInterface has dark/light support; other components are single-theme
3. 90+ inline ternary operators for theme switching (unmaintainable)
4. No CSS custom properties or design tokens
5. Header navigation only - no sidebar
6. Limited stats visibility
7. No toast notifications (uses `alert()`)
8. Sources returned by API but not displayed as citations

### Current File Structure
```
services/webapp/src/
├── app.css                          # Just "@import tailwindcss"
├── app.html                         # Base HTML template
├── lib/
│   ├── components/
│   │   ├── Header.svelte            # Top nav (dark-only)
│   │   ├── ChatInterface.svelte     # Chat UI (has dark/light via ternaries)
│   │   ├── FileUpload.svelte        # Upload buttons (light-only)
│   │   └── DocumentTable.svelte     # Doc table (light-only)
│   ├── stores/
│   │   ├── chat.ts                  # Chat state
│   │   ├── documents.ts             # Documents state
│   │   └── theme.ts                 # Theme toggle (hardcoded 'dark' default)
│   └── utils/
│       ├── api.ts                   # API functions
│       └── session.ts               # Session ID management
└── routes/
    ├── +layout.svelte               # Layout with Header
    ├── +page.svelte                 # Chat page (current home)
    ├── about/+page.svelte           # System info (light-only)
    ├── admin/+page.svelte           # Document management
    └── api/                         # API route handlers
```

---

## Phase 1: Theming Foundation

### 1.1 CSS Custom Properties
**File:** `services/webapp/src/app.css`

Add design tokens for semantic colors supporting dark/light modes:

```css
@import "tailwindcss";

:root {
  /* Color Palette */
  --color-gray-50: 249 250 251;
  --color-gray-100: 243 244 246;
  --color-gray-200: 229 231 235;
  --color-gray-300: 209 213 219;
  --color-gray-400: 156 163 175;
  --color-gray-500: 107 114 128;
  --color-gray-600: 75 85 99;
  --color-gray-700: 55 65 81;
  --color-gray-800: 31 41 55;
  --color-gray-900: 17 24 39;
  --color-gray-950: 3 7 18;

  --color-primary-400: 96 165 250;
  --color-primary-500: 59 130 246;
  --color-primary-600: 37 99 235;
  --color-primary-700: 29 78 216;

  --color-success-500: 34 197 94;
  --color-error-500: 239 68 68;
  --color-warning-500: 234 179 8;

  /* Semantic Tokens (Light Mode) */
  --surface-base: var(--color-gray-50);
  --surface-raised: 255 255 255;
  --surface-overlay: 255 255 255;
  --surface-sunken: var(--color-gray-100);

  --on-surface: var(--color-gray-900);
  --on-surface-muted: var(--color-gray-600);
  --on-surface-subtle: var(--color-gray-400);

  --border-default: var(--color-gray-200);
  --primary: var(--color-primary-600);
  --primary-hover: var(--color-primary-700);

  /* Sidebar */
  --sidebar-width-expanded: 240px;
  --sidebar-width-collapsed: 64px;
  --sidebar-bg: var(--color-gray-900);
  --sidebar-text: var(--color-gray-300);
  --sidebar-hover: var(--color-gray-800);
  --sidebar-active: var(--color-primary-600);

  /* Chat */
  --chat-user-bg: var(--color-primary-600);
  --chat-assistant-bg: var(--color-gray-100);
  --chat-assistant-text: var(--color-gray-900);

  /* Citation badge */
  --citation-bg: var(--color-primary-500);
}

/* Dark Mode */
.dark {
  --surface-base: var(--color-gray-950);
  --surface-raised: var(--color-gray-900);
  --surface-overlay: var(--color-gray-800);
  --surface-sunken: var(--color-gray-900);

  --on-surface: var(--color-gray-100);
  --on-surface-muted: var(--color-gray-400);
  --on-surface-subtle: var(--color-gray-600);

  --border-default: var(--color-gray-800);
  --primary: var(--color-primary-500);
  --primary-hover: var(--color-primary-400);

  --chat-assistant-bg: var(--color-gray-800);
  --chat-assistant-text: var(--color-gray-100);
}

/* Utility Classes */
.bg-surface { background-color: rgb(var(--surface-base)); }
.bg-surface-raised { background-color: rgb(var(--surface-raised)); }
.bg-surface-overlay { background-color: rgb(var(--surface-overlay)); }
.text-on-surface { color: rgb(var(--on-surface)); }
.text-muted { color: rgb(var(--on-surface-muted)); }
.border-default { border-color: rgb(var(--border-default)); }
```

### 1.2 Theme Store with Browser Preference
**File:** `services/webapp/src/lib/stores/theme.svelte.ts` (new, replaces theme.ts)

```typescript
import { browser } from '$app/environment';

export type Theme = 'dark' | 'light' | 'system';

function getSystemTheme(): 'dark' | 'light' {
  if (!browser) return 'dark';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function createThemeStore() {
  const stored = browser ? localStorage.getItem('theme') as Theme : null;
  let preference = $state<Theme>(stored || 'system');
  let resolved = $state<'dark' | 'light'>(
    preference === 'system' ? getSystemTheme() : preference
  );

  if (browser) {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', (e) => {
      if (preference === 'system') {
        resolved = e.matches ? 'dark' : 'light';
        applyTheme(resolved);
      }
    });
    applyTheme(resolved);
  }

  function applyTheme(theme: 'dark' | 'light') {
    if (!browser) return;
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }

  return {
    get preference() { return preference; },
    get resolved() { return resolved; },
    get isDark() { return resolved === 'dark'; },

    setPreference(value: Theme) {
      preference = value;
      resolved = value === 'system' ? getSystemTheme() : value;
      if (browser) {
        localStorage.setItem('theme', value);
        applyTheme(resolved);
      }
    },

    toggle() {
      this.setPreference(resolved === 'dark' ? 'light' : 'dark');
    }
  };
}

export const theme = createThemeStore();
```

### 1.3 Flash Prevention
**File:** `services/webapp/src/app.html`

```html
<!doctype html>
<html lang="en" class="dark">
  <head>
    <meta charset="utf-8" />
    <link rel="icon" href="%sveltekit.assets%/favicon.png" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="dark light" />
    <script>
      (function() {
        const stored = localStorage.getItem('theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const isDark = stored === 'dark' || (stored === 'system' || !stored) && prefersDark;
        document.documentElement.classList.toggle('dark', isDark);
      })();
    </script>
    %sveltekit.head%
  </head>
  <body data-sveltekit-preload-data="hover" class="bg-surface text-on-surface">
    <div style="display: contents">%sveltekit.body%</div>
  </body>
</html>
```

### 1.4 Tailwind Config
**File:** `services/webapp/tailwind.config.js`

```javascript
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: {
          base: 'rgb(var(--surface-base) / <alpha-value>)',
          raised: 'rgb(var(--surface-raised) / <alpha-value>)',
          overlay: 'rgb(var(--surface-overlay) / <alpha-value>)',
          sunken: 'rgb(var(--surface-sunken) / <alpha-value>)',
        },
        'on-surface': {
          DEFAULT: 'rgb(var(--on-surface) / <alpha-value>)',
          muted: 'rgb(var(--on-surface-muted) / <alpha-value>)',
        },
        primary: {
          DEFAULT: 'rgb(var(--primary) / <alpha-value>)',
          hover: 'rgb(var(--primary-hover) / <alpha-value>)',
        },
        sidebar: {
          bg: 'rgb(var(--sidebar-bg) / <alpha-value>)',
          text: 'rgb(var(--sidebar-text) / <alpha-value>)',
          hover: 'rgb(var(--sidebar-hover) / <alpha-value>)',
          active: 'rgb(var(--sidebar-active) / <alpha-value>)',
        }
      },
      width: {
        'sidebar-expanded': 'var(--sidebar-width-expanded)',
        'sidebar-collapsed': 'var(--sidebar-width-collapsed)',
      },
    },
  },
};
```

---

## Phase 2: Collapsible Sidebar

### 2.1 Sidebar Store
**File:** `services/webapp/src/lib/stores/sidebar.svelte.ts` (new)

```typescript
import { browser } from '$app/environment';

function createSidebarStore() {
  const stored = browser ? localStorage.getItem('sidebar-collapsed') : null;
  let collapsed = $state(stored === 'true');

  return {
    get collapsed() { return collapsed; },
    toggle() {
      collapsed = !collapsed;
      if (browser) localStorage.setItem('sidebar-collapsed', String(collapsed));
    },
    setCollapsed(value: boolean) {
      collapsed = value;
      if (browser) localStorage.setItem('sidebar-collapsed', String(value));
    }
  };
}

export const sidebar = createSidebarStore();
```

### 2.2 Sidebar Component
**File:** `services/webapp/src/lib/components/layout/Sidebar.svelte` (new)

Features:
- Fixed left position, full height
- Logo area at top ("RAG System" or "R" when collapsed)
- Navigation items: Documents, Chat, Dashboard
- Theme toggle at bottom (dark/light/system)
- Collapse/expand button
- Smooth width transition (240px ↔ 64px)
- Active page indicator
- Tooltips when collapsed

### 2.3 SidebarItem Component
**File:** `services/webapp/src/lib/components/layout/SidebarItem.svelte` (new)

- Icon + label (label hidden when collapsed)
- Hover and active states
- Tooltip when collapsed

### 2.4 ThemeToggle Component
**File:** `services/webapp/src/lib/components/layout/ThemeToggle.svelte` (new)

Extract theme toggle into reusable component with dark/light/system options.

### 2.5 Update Layout
**File:** `services/webapp/src/routes/+layout.svelte`

```svelte
<script lang="ts">
  import { sidebar } from '$lib/stores/sidebar.svelte';
  import Sidebar from '$lib/components/layout/Sidebar.svelte';
  import ToastContainer from '$lib/components/feedback/ToastContainer.svelte';
  import '../app.css';

  let { children } = $props();
</script>

<div class="min-h-screen bg-surface">
  <Sidebar />
  <main
    class="transition-all duration-200 min-h-screen"
    class:ml-[240px]={!sidebar.collapsed}
    class:ml-16={sidebar.collapsed}
  >
    {@render children()}
  </main>
  <ToastContainer />
</div>
```

---

## Phase 3: Route Restructure

### 3.1 New Route Structure
```
/              → Redirect to /documents
/documents     → Document management (current /admin)
/chat          → Chat interface (current /)
/dashboard     → System stats (new, replaces /about)
```

### 3.2 Files to Create/Move
- `services/webapp/src/routes/+page.svelte` → Redirect to /documents
- `services/webapp/src/routes/documents/+page.svelte` → Move from admin
- `services/webapp/src/routes/chat/+page.svelte` → Move current home
- `services/webapp/src/routes/dashboard/+page.svelte` → New stats page

### 3.3 Delete
- `services/webapp/src/routes/admin/` (moved to /documents)
- `services/webapp/src/routes/about/` (replaced by /dashboard)
- `services/webapp/src/lib/components/Header.svelte` (replaced by Sidebar)

---

## Phase 4: Toast Notification System

### 4.1 Toast Store
**File:** `services/webapp/src/lib/stores/toast.svelte.ts` (new)

```typescript
export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

function createToastStore() {
  let toasts = $state<Toast[]>([]);

  return {
    get items() { return toasts; },

    add(type: ToastType, message: string, duration = 5000) {
      const id = crypto.randomUUID();
      toasts = [...toasts, { id, type, message, duration }];
      if (duration > 0) setTimeout(() => this.remove(id), duration);
      return id;
    },

    remove(id: string) {
      toasts = toasts.filter(t => t.id !== id);
    },

    success(msg: string) { return this.add('success', msg); },
    error(msg: string) { return this.add('error', msg, 8000); },
    warning(msg: string) { return this.add('warning', msg); },
    info(msg: string) { return this.add('info', msg); },
  };
}

export const toast = createToastStore();
```

### 4.2 Toast Components
**Files:**
- `services/webapp/src/lib/components/feedback/Toast.svelte` (new)
- `services/webapp/src/lib/components/feedback/ToastContainer.svelte` (new)

Position: bottom-right, stacked, animated entry/exit.

### 4.3 Confirmation Dialog
**File:** `services/webapp/src/lib/components/feedback/ConfirmDialog.svelte` (new)

Modal dialog for destructive actions (delete documents).

---

## Phase 5: Chat Interface with Citations

### 5.1 ChatMessage Component
**File:** `services/webapp/src/lib/components/chat/ChatMessage.svelte` (new)

- Parse `[1]`, `[2]` markers in response text
- Render clickable citation badges
- Track expanded citations per message

### 5.2 Citation Component
**File:** `services/webapp/src/lib/components/chat/Citation.svelte` (new)

```svelte
<script lang="ts">
  import type { Source } from '$lib/utils/api';

  interface Props {
    index: number;
    source: Source;
    expanded?: boolean;
    onToggle: () => void;
  }

  let { index, source, expanded = false, onToggle }: Props = $props();
</script>

<button
  onclick={onToggle}
  class="inline-flex items-center justify-center w-5 h-5 text-xs font-medium rounded-full
         bg-primary text-white hover:bg-primary-hover transition-colors cursor-pointer"
  title={source.document_name}
>
  {index}
</button>

{#if expanded}
  <div class="mt-2 p-3 rounded-lg bg-surface-sunken border border-default text-sm">
    <div class="font-medium text-on-surface mb-1">{source.document_name}</div>
    <p class="text-muted whitespace-pre-wrap">{source.excerpt}</p>
    {#if source.distance != null}
      <div class="mt-2 text-xs text-on-surface-subtle">
        Relevance: {((1 - source.distance) * 100).toFixed(1)}%
      </div>
    {/if}
  </div>
{/if}
```

### 5.3 Update ChatInterface
**File:** `services/webapp/src/lib/components/ChatInterface.svelte`

- Use ChatMessage component for rendering
- Pass sources to messages
- Apply CSS custom properties (remove ternary operators)
- Extract input to ChatInput component

### 5.4 Update API Response Handling
**File:** `services/webapp/src/lib/utils/api.ts`

Ensure sources are parsed and passed to chat store.

### 5.5 Update Chat Store
**File:** `services/webapp/src/lib/stores/chat.ts`

Add sources array to Message type.

---

## Phase 6: Document Management Enhancements

### 6.1 DocumentTable Updates
**File:** `services/webapp/src/lib/components/DocumentTable.svelte`

- Apply CSS custom properties for dark/light support
- Add column sorting (name, type, size, chunks)
- Add search/filter input
- Replace `alert()` with toast notifications
- Use ConfirmDialog for delete actions

### 6.2 FileUpload Updates
**File:** `services/webapp/src/lib/components/FileUpload.svelte`

- Apply CSS custom properties
- Toast notifications for upload start/complete/error

---

## Phase 7: Stats Dashboard

### 7.1 Backend Endpoint
**File:** `services/rag_server/main.py`

Add `GET /stats` endpoint:

```python
from pydantic import BaseModel

class SystemStatsResponse(BaseModel):
    total_documents: int
    total_embeddings: int
    total_chunks: int
    total_size_bytes: int
    hybrid_search_enabled: bool
    contextual_retrieval_enabled: bool
    reranker_enabled: bool
    retrieval_top_k: int
    rrf_k: int
    services: dict  # {"chromadb": "healthy", "redis": "healthy", "ollama": "healthy"}

@app.get("/stats", response_model=SystemStatsResponse)
async def get_system_stats():
    """Get comprehensive system statistics"""
    index = get_or_create_collection()
    collection = index._vector_store._collection
    documents = list_documents(index)

    # Check service health
    services = {}
    try:
        collection.count()
        services['chromadb'] = 'healthy'
    except Exception:
        services['chromadb'] = 'unhealthy'

    # Redis health check
    try:
        redis_client.ping()
        services['redis'] = 'healthy'
    except Exception:
        services['redis'] = 'unhealthy'

    # Ollama health check
    try:
        import httpx
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        services['ollama'] = 'healthy' if resp.status_code == 200 else 'unhealthy'
    except Exception:
        services['ollama'] = 'unhealthy'

    return SystemStatsResponse(
        total_documents=len(documents),
        total_embeddings=collection.count(),
        total_chunks=sum(d.get('chunks', 0) for d in documents),
        total_size_bytes=sum(d.get('file_size_bytes', 0) for d in documents),
        hybrid_search_enabled=os.getenv('ENABLE_HYBRID_SEARCH', 'true').lower() == 'true',
        contextual_retrieval_enabled=os.getenv('ENABLE_CONTEXTUAL_RETRIEVAL', 'false').lower() == 'true',
        reranker_enabled=os.getenv('ENABLE_RERANKER', 'true').lower() == 'true',
        retrieval_top_k=int(os.getenv('RETRIEVAL_TOP_K', '10')),
        rrf_k=int(os.getenv('RRF_K', '60')),
        services=services
    )
```

### 7.2 API Proxy
**File:** `services/webapp/src/routes/api/stats/+server.ts` (new)

Proxy to backend `/stats` endpoint.

### 7.3 Dashboard Components
**Files:**
- `services/webapp/src/lib/components/stats/StatsCard.svelte` (new) - Display stat with label
- `services/webapp/src/lib/components/stats/ServiceStatus.svelte` (new) - Health indicator dot
- `services/webapp/src/lib/components/stats/ConfigDisplay.svelte` (new) - RAG config toggle states

### 7.4 Dashboard Page
**File:** `services/webapp/src/routes/dashboard/+page.svelte` (new)

Layout:
- Service health indicators (top row)
- Stats cards (documents, embeddings, chunks, storage)
- RAG configuration panel
- Model information

---

## Phase 8: Final Polish

### 8.1 Loading States
- Add LoadingSkeleton component
- Apply to documents table, dashboard stats

### 8.2 Empty States
- Chat: Welcome message with guidance
- Documents: Upload prompt when empty

### 8.3 Dependencies
**File:** `services/webapp/package.json`

Add: `lucide-svelte` for icons

---

## Files Summary

### New Files (16)
```
services/webapp/src/lib/stores/theme.svelte.ts
services/webapp/src/lib/stores/sidebar.svelte.ts
services/webapp/src/lib/stores/toast.svelte.ts
services/webapp/src/lib/components/layout/Sidebar.svelte
services/webapp/src/lib/components/layout/SidebarItem.svelte
services/webapp/src/lib/components/layout/ThemeToggle.svelte
services/webapp/src/lib/components/chat/ChatMessage.svelte
services/webapp/src/lib/components/chat/Citation.svelte
services/webapp/src/lib/components/feedback/Toast.svelte
services/webapp/src/lib/components/feedback/ToastContainer.svelte
services/webapp/src/lib/components/feedback/ConfirmDialog.svelte
services/webapp/src/lib/components/stats/StatsCard.svelte
services/webapp/src/lib/components/stats/ServiceStatus.svelte
services/webapp/src/lib/components/stats/ConfigDisplay.svelte
services/webapp/src/routes/dashboard/+page.svelte
services/webapp/src/routes/api/stats/+server.ts
```

### Modified Files (10)
```
services/webapp/src/app.css                              # Add CSS custom properties
services/webapp/src/app.html                             # Add theme flash prevention
services/webapp/tailwind.config.js                       # Extend with semantic colors
services/webapp/src/routes/+layout.svelte                # Sidebar layout
services/webapp/src/routes/+page.svelte                  # Redirect to /documents
services/webapp/src/routes/admin/+page.svelte            # Move to /documents
services/webapp/src/lib/components/ChatInterface.svelte  # Use new components
services/webapp/src/lib/components/DocumentTable.svelte  # Sorting, dark mode, toasts
services/webapp/src/lib/components/FileUpload.svelte     # Dark mode, toasts
services/webapp/src/lib/stores/chat.ts                   # Add sources to Message
services/rag_server/main.py                              # Add /stats endpoint
```

### Delete Files (3)
```
services/webapp/src/lib/components/Header.svelte         # Replaced by Sidebar
services/webapp/src/lib/stores/theme.ts                  # Replaced by theme.svelte.ts
services/webapp/src/routes/about/+page.svelte            # Replaced by /dashboard
```

---

## Implementation Order

1. **Phase 1** - Theming (foundation for everything else) - COMPLETED
2. **Phase 2** - Sidebar (navigation structure) - COMPLETED
3. **Phase 3** - Routes (page reorganization) - COMPLETED
4. **Phase 4** - Toasts (feedback system) - COMPLETED
5. **Phase 5** - Chat citations - COMPLETED
6. **Phase 6** - Document enhancements
7. **Phase 7** - Stats dashboard
8. **Phase 8** - Polish

