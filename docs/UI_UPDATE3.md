# WebApp Complete Rewrite: Svelte 5 + Tailwind 4.1 + svelte-ux@next

## Overview
Complete UI rewrite using:
- **Svelte 5** with runes ($state, $derived, $effect, $props)
- **Tailwind CSS 4.1** (CSS-first configuration)
- **svelte-ux@next** (2.0.0-next.21) for UI components
- **layerchart@next** (2.0.0-next.43) for charts
- **@layerstack/tailwind@next** (2.0.0-next.19) for theme system

**Themes**: Light = "nord", Dark = "dim" (DaisyUI themes)

## Pages to Build
1. **Documents** - Upload, view, delete documents (default page)
2. **Chat** - RAG chat interface to query documents
3. **Dashboard** - System stats, charts, service health

## Files to Modify/Create

### Configuration Files

| File | Action | Purpose |
|------|--------|---------|
| `package.json` | Modify | Update dependencies |
| `tailwind.config.js` | **DELETE** | Not needed for Tailwind 4 |
| `src/app.css` | Rewrite | Tailwind 4 CSS imports |
| `vite.config.ts` | Keep | No changes needed |
| `svelte.config.js` | Keep | No changes needed |

### Layout & Theme

| File | Action | Purpose |
|------|--------|---------|
| `src/routes/+layout.svelte` | Rewrite | AppLayout + settings + ThemeSwitch |
| `src/routes/+layout.ts` | Create | `ssr = false` for theme |
| `src/lib/components/layout/Sidebar.svelte` | Rewrite | Navigation using svelte-ux |
| `src/lib/components/layout/SidebarItem.svelte` | Rewrite | Nav items with svelte-ux Button |
| `src/lib/components/layout/ThemeSelect.svelte` | **DELETE** | Replaced by ThemeSwitch |
| `src/lib/stores/theme.svelte.ts` | **DELETE** | Handled by svelte-ux settings |
| `src/lib/stores/sidebar.svelte.ts` | Rewrite | Simplify with svelte-ux showDrawer |

### Pages

| File | Action | Purpose |
|------|--------|---------|
| `src/routes/+page.svelte` | Keep | Redirect to /documents |
| `src/routes/documents/+page.svelte` | Rewrite | Document management |
| `src/routes/chat/+page.svelte` | Rewrite | Chat interface |
| `src/routes/dashboard/+page.svelte` | Rewrite | Dashboard with LayerChart |

### Components

| File | Action | Purpose |
|------|--------|---------|
| `src/lib/components/ChatInterface.svelte` | Rewrite | Chat UI |
| `src/lib/components/DocumentTable.svelte` | Rewrite | Documents list |
| `src/lib/components/FileUpload.svelte` | Rewrite | Upload UI |
| `src/lib/components/chat/ChatMessage.svelte` | Rewrite | Message bubble |
| `src/lib/components/chat/Citation.svelte` | Keep/Update | Citation display |
| `src/lib/components/feedback/*.svelte` | Simplify | Use svelte-ux Dialog/Toast |
| `src/lib/components/charts/*.svelte` | Rewrite | Use LayerChart |

### Stores & Utils

| File | Action | Purpose |
|------|--------|---------|
| `src/lib/stores/chat.ts` | Keep | Chat state |
| `src/lib/stores/documents.ts` | Keep | Documents state |
| `src/lib/utils/api.ts` | Keep | API calls |
| `src/lib/utils/session.ts` | Keep | Session management |

## Implementation Order

### Phase 1: Foundation
1. Update package.json dependencies
2. Delete tailwind.config.js
3. Rewrite app.css for Tailwind 4
4. Update +layout.svelte with svelte-ux settings and AppLayout
5. Create +layout.ts with ssr = false
6. Run `npm install` and verify build

### Phase 2: Layout Components
1. Rewrite Sidebar.svelte
2. Rewrite SidebarItem.svelte
3. Delete ThemeSelect.svelte (replaced by ThemeSwitch)
4. Delete theme.svelte.ts store

### Phase 3: Documents Page
1. Rewrite FileUpload.svelte
2. Rewrite DocumentTable.svelte
3. Rewrite documents/+page.svelte

### Phase 4: Chat Page
1. Rewrite ChatMessage.svelte
2. Rewrite ChatInterface.svelte
3. Rewrite chat/+page.svelte

### Phase 5: Dashboard Page
1. Rewrite chart components with LayerChart
2. Rewrite dashboard/+page.svelte

### Phase 6: Polish
1. Update feedback components
2. Run build and fix any issues

## Key Code Patterns

### app.css (Tailwind 4)
```css
@import 'tailwindcss';
@import '@layerstack/tailwind/core.css';
@import '@layerstack/tailwind/themes/daisy.css';

:root {
  --sidebar-width-expanded: 240px;
  --sidebar-width-collapsed: 64px;
}
```

### +layout.svelte
```svelte
<script lang="ts">
  import { settings, AppLayout, AppBar, ThemeSwitch, Button } from 'svelte-ux';
  import { Menu } from 'lucide-svelte';
  import '../app.css';

  let { children } = $props();

  const { showDrawer } = settings({
    themes: {
      light: ['nord'],
      dark: ['dim']
    }
  });
</script>

<AppLayout>
  <AppBar slot="header">
    <Button icon={Menu} on:click={() => ($showDrawer = !$showDrawer)} />
    <span class="flex-1">RAG System</span>
    <ThemeSwitch />
  </AppBar>

  <nav slot="nav" class="p-2">
    <!-- Navigation items -->
  </nav>

  {@render children()}
</AppLayout>
```

### Svelte 5 Runes Pattern
```svelte
<script lang="ts">
  // Props with $props()
  let { data, onAction } = $props<{ data: Item[]; onAction: () => void }>();

  // State with $state
  let isLoading = $state(false);
  let items = $state<Item[]>([]);

  // Derived with $derived
  let filtered = $derived(items.filter(i => i.active));

  // Effects with $effect
  $effect(() => {
    console.log('Items changed:', items.length);
  });
</script>
```

### Color Classes
- Surfaces: `bg-surface-100`, `bg-surface-200`, `bg-surface-300`
- Text: `text-surface-content`
- Primary: `bg-primary`, `text-primary-content`
- Status: `bg-success`, `bg-warning`, `bg-danger`, `bg-info`

## Dependencies Update

```json
{
  "devDependencies": {
    "svelte-ux": "2.0.0-next.21",
    "layerchart": "2.0.0-next.43",
    "@layerstack/tailwind": "2.0.0-next.19",
    "@tailwindcss/vite": "^4.0.0",
    "tailwindcss": "^4.0.0"
  }
}
```
