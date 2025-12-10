# UI Revamp Plan: Svelte UX + LayerChart + Tailwind 4

## Executive Summary

Complete UI overhaul migrating to **svelte-ux** component library and **LayerChart** for visualizations. This creates a clean, extensible foundation supporting dark/light themes with professional design patterns suitable for dashboard-heavy applications.

**Target Stack:**
- SvelteKit 2 + Svelte 5
- Tailwind CSS 4 (already installed)
- svelte-ux (UI components, theming, utilities)
- LayerChart (data visualizations)
- lucide-svelte (icons - already installed)

---

## Current State Analysis

### Existing Setup
- **Framework:** SvelteKit 2 + Svelte 5 ✓
- **Styling:** Tailwind CSS 4 ✓ (already migrated)
- **Icons:** lucide-svelte ✓
- **Theme:** Custom CSS variables with dark/light support ✓
- **Components:** Custom sidebar, toast, chat interface

### What's Working Well
1. CSS custom properties for theming (semantic tokens)
2. Dark/light mode with `.dark` class toggle
3. Sidebar navigation pattern
4. Toast notification system

### Gaps to Address
1. No component library (everything hand-rolled)
2. No data visualization capability
3. Limited form components
4. No charts for dashboard metrics
5. Inconsistent component patterns

---

## Phase 1: Install Dependencies

### 1.1 Package Installation

```bash
cd services/webapp
npm install svelte-ux layerchart @layerstack/tailwind
```

### 1.2 Updated package.json

```json
{
  "dependencies": {
    "@types/node": "^22.10.2",
    "lucide-svelte": "^0.556.0",
    "svelte-ux": "^1.0.0",
    "layerchart": "^2.0.0"
  },
  "devDependencies": {
    "@sveltejs/adapter-node": "^5.2.9",
    "@sveltejs/kit": "^2.17.4",
    "@sveltejs/vite-plugin-svelte": "^5.0.4",
    "@tailwindcss/vite": "^4.0.0",
    "@layerstack/tailwind": "^1.0.0",
    "svelte": "^5.18.3",
    "svelte-check": "^4.1.3",
    "tailwindcss": "^4.0.0",
    "tslib": "^2.8.1",
    "typescript": "^5.7.2",
    "vite": "^6.0.7"
  }
}
```

---

## Phase 2: Tailwind 4 + Svelte UX Integration

### 2.1 Update app.css

Replace current `app.css` with svelte-ux compatible configuration:

```css
/* services/webapp/src/app.css */
@import 'tailwindcss';
@import '@layerstack/tailwind/core.css';
@import '@layerstack/tailwind/utils.css';
@import '@layerstack/tailwind/themes/basic.css';

/* Include svelte-ux and layerchart component styles */
@source '../../node_modules/svelte-ux/dist';
@source '../../node_modules/layerchart/dist';

/* ============================================
   Custom Theme Variables
   ============================================ */

:root {
  /* Brand Colors */
  --color-brand-50: 239 246 255;
  --color-brand-100: 219 234 254;
  --color-brand-200: 191 219 254;
  --color-brand-300: 147 197 253;
  --color-brand-400: 96 165 250;
  --color-brand-500: 59 130 246;
  --color-brand-600: 37 99 235;
  --color-brand-700: 29 78 216;
  --color-brand-800: 30 64 175;
  --color-brand-900: 30 58 138;

  /* Semantic Colors - Light Mode */
  --color-primary: var(--color-brand-600);
  --color-secondary: oklch(69.71% 0.329 342.55);
  --color-accent: oklch(76.76% 0.184 183.61);

  /* Surface Colors - Light Mode */
  --color-surface-100: 250 250 250;
  --color-surface-200: 244 244 245;
  --color-surface-300: 228 228 231;
  --color-surface-content: 24 24 27;

  /* Status Colors */
  --color-success: 34 197 94;
  --color-warning: 234 179 8;
  --color-danger: 239 68 68;
  --color-info: 59 130 246;

  /* Chart Colors (LayerChart) */
  --color-chart-1: var(--color-brand-500);
  --color-chart-2: 168 85 247;
  --color-chart-3: 34 197 94;
  --color-chart-4: 251 146 60;
  --color-chart-5: 236 72 153;
  --color-chart-6: 20 184 166;

  /* Sidebar (keep existing) */
  --sidebar-width-expanded: 240px;
  --sidebar-width-collapsed: 64px;
  --sidebar-bg: 23 23 23;
  --sidebar-text: 212 212 216;
  --sidebar-hover: 39 39 42;
  --sidebar-active: var(--color-brand-600);

  /* Chat Colors */
  --chat-user-bg: var(--color-brand-600);
  --chat-assistant-bg: 244 244 245;
  --chat-assistant-text: 24 24 27;
}

/* ============================================
   Dark Mode Overrides
   ============================================ */

.dark {
  --color-primary: var(--color-brand-500);
  --color-secondary: oklch(74.8% 0.26 342.55);
  --color-accent: oklch(74.51% 0.167 183.61);

  /* Surface Colors - Dark Mode */
  --color-surface-100: 24 24 27;
  --color-surface-200: 39 39 42;
  --color-surface-300: 63 63 70;
  --color-surface-content: 250 250 250;

  /* Sidebar */
  --sidebar-bg: 9 9 11;
  --sidebar-hover: 39 39 42;

  /* Chat */
  --chat-assistant-bg: 39 39 42;
  --chat-assistant-text: 250 250 250;
}

/* ============================================
   Svelte UX Theme Customization
   ============================================ */

:root {
  /* Map to svelte-ux theme variables */
  --color-primary: rgb(var(--color-brand-600));
  --color-primary-content: white;

  &.dark {
    --color-primary: rgb(var(--color-brand-500));
  }
}

/* ============================================
   Utility Classes (keep existing)
   ============================================ */

.bg-surface { background-color: rgb(var(--color-surface-100)); }
.bg-surface-raised { background-color: rgb(var(--color-surface-200)); }
.bg-surface-overlay { background-color: rgb(var(--color-surface-300)); }
.text-on-surface { color: rgb(var(--color-surface-content)); }
.text-muted { color: rgb(var(--color-surface-content) / 0.6); }
.text-subtle { color: rgb(var(--color-surface-content) / 0.4); }
.border-default { border-color: rgb(var(--color-surface-300)); }
```

### 2.2 Remove tailwind.config.js

Tailwind 4 uses CSS-based configuration. The `tailwind.config.js` can be simplified or removed entirely since configuration moves to `app.css`.

**Option A: Delete entirely** (recommended for Tailwind 4)

```bash
rm services/webapp/tailwind.config.js
```

**Option B: Minimal config for content paths**

```javascript
// services/webapp/tailwind.config.js
export default {
  content: [
    './src/**/*.{html,js,svelte,ts}',
    './node_modules/svelte-ux/**/*.{svelte,js}',
    './node_modules/layerchart/**/*.{svelte,js}'
  ]
};
```

---

## Phase 3: Svelte UX Setup

### 3.1 Initialize Settings in Layout

Update `+layout.svelte` to initialize svelte-ux:

```svelte
<!-- services/webapp/src/routes/+layout.svelte -->
<script lang="ts">
  import { settings, ThemeInit } from 'svelte-ux';
  import { sidebar } from '$lib/stores/sidebar.svelte';
  import Sidebar from '$lib/components/layout/Sidebar.svelte';
  import ToastContainer from '$lib/components/feedback/ToastContainer.svelte';
  import '../app.css';

  // Initialize svelte-ux settings
  settings({
    themes: {
      light: ['light'],
      dark: ['dark']
    }
  });

  let { children } = $props();
</script>

<!-- Prevent theme flash -->
<ThemeInit />

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

### 3.2 Theme Integration

Update theme store to work with svelte-ux:

```typescript
// services/webapp/src/lib/stores/theme.svelte.ts
import { browser } from '$app/environment';
import { getSettings } from 'svelte-ux';

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

    // Sync with svelte-ux if available
    try {
      const { currentTheme } = getSettings();
      currentTheme?.setTheme(theme);
    } catch {
      // svelte-ux not initialized yet
    }
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

---

## Phase 4: Component Migration Strategy

### 4.1 Components to Replace with Svelte UX

| Current Component | Svelte UX Replacement | Priority |
|-------------------|----------------------|----------|
| Custom buttons | `Button` | High |
| Custom dialogs | `Dialog` | High |
| Toast system | Keep custom (good) | - |
| Form inputs | `TextField`, `Field` | High |
| Dropdown menus | `Menu`, `MenuItem` | Medium |
| Tabs (future) | `Tabs`, `Tab` | Medium |
| Cards | `Card` (if available) or custom | Low |

### 4.2 Component Wrapper Pattern

Create wrapper components to maintain consistent API while using svelte-ux internally:

```svelte
<!-- services/webapp/src/lib/components/ui/Button.svelte -->
<script lang="ts">
  import { Button as SvelteUXButton } from 'svelte-ux';
  import type { Snippet } from 'svelte';

  interface Props {
    variant?: 'default' | 'outline' | 'ghost' | 'danger';
    size?: 'sm' | 'md' | 'lg';
    disabled?: boolean;
    loading?: boolean;
    href?: string;
    onclick?: () => void;
    children: Snippet;
  }

  let {
    variant = 'default',
    size = 'md',
    disabled = false,
    loading = false,
    href,
    onclick,
    children
  }: Props = $props();

  // Map our variants to svelte-ux variants
  const variantMap = {
    default: 'fill',
    outline: 'outline',
    ghost: 'text',
    danger: 'fill'
  };

  const colorMap = {
    default: 'primary',
    outline: 'primary',
    ghost: 'default',
    danger: 'danger'
  };
</script>

<SvelteUXButton
  variant={variantMap[variant]}
  color={colorMap[variant]}
  {size}
  {disabled}
  {loading}
  {href}
  on:click={onclick}
>
  {@render children()}
</SvelteUXButton>
```

### 4.3 Form Components

```svelte
<!-- services/webapp/src/lib/components/ui/Input.svelte -->
<script lang="ts">
  import { TextField } from 'svelte-ux';

  interface Props {
    label?: string;
    placeholder?: string;
    value?: string;
    type?: 'text' | 'email' | 'password' | 'number';
    error?: string;
    disabled?: boolean;
    required?: boolean;
  }

  let {
    label,
    placeholder,
    value = $bindable(''),
    type = 'text',
    error,
    disabled = false,
    required = false
  }: Props = $props();
</script>

<TextField
  {label}
  {placeholder}
  bind:value
  {type}
  {error}
  {disabled}
  {required}
/>
```

---

## Phase 5: LayerChart Integration

### 5.1 Chart Wrapper Components

Create reusable chart components for the dashboard:

```svelte
<!-- services/webapp/src/lib/components/charts/StatCard.svelte -->
<script lang="ts">
  import { Card } from 'svelte-ux';
  import { Chart, Svg, Area, Axis, Tooltip } from 'layerchart';
  import { scaleTime, scaleLinear } from 'd3-scale';

  interface Props {
    title: string;
    value: string | number;
    subtitle?: string;
    trend?: number; // percentage change
    sparklineData?: { date: Date; value: number }[];
    icon?: any; // Lucide icon component
  }

  let { title, value, subtitle, trend, sparklineData, icon: Icon }: Props = $props();

  const trendColor = trend && trend > 0 ? 'text-green-500' : trend && trend < 0 ? 'text-red-500' : 'text-muted';
  const trendIcon = trend && trend > 0 ? '↑' : trend && trend < 0 ? '↓' : '';
</script>

<div class="bg-surface-raised rounded-lg p-4 border border-default">
  <div class="flex items-start justify-between mb-2">
    <div class="flex items-center gap-2">
      {#if Icon}
        <Icon class="w-4 h-4 text-muted" />
      {/if}
      <span class="text-sm text-muted">{title}</span>
    </div>
    {#if trend !== undefined}
      <span class="text-xs {trendColor}">
        {trendIcon} {Math.abs(trend)}%
      </span>
    {/if}
  </div>

  <div class="text-2xl font-semibold text-on-surface mb-1">
    {value}
  </div>

  {#if subtitle}
    <div class="text-xs text-subtle">{subtitle}</div>
  {/if}

  {#if sparklineData && sparklineData.length > 0}
    <div class="h-12 mt-3">
      <Chart
        data={sparklineData}
        x="date"
        xScale={scaleTime()}
        y="value"
        yScale={scaleLinear()}
        yNice
        padding={{ top: 4, bottom: 4, left: 0, right: 0 }}
      >
        <Svg>
          <Area class="fill-primary/20" line={{ class: 'stroke-primary stroke-2' }} />
        </Svg>
      </Chart>
    </div>
  {/if}
</div>
```

### 5.2 Area Chart Component

```svelte
<!-- services/webapp/src/lib/components/charts/AreaChart.svelte -->
<script lang="ts">
  import { Chart, Svg, Area, Axis, Tooltip, TooltipItem, Highlight } from 'layerchart';
  import { scaleTime, scaleLinear } from 'd3-scale';
  import { format } from 'date-fns';

  interface DataPoint {
    date: Date;
    value: number;
    label?: string;
  }

  interface Props {
    data: DataPoint[];
    height?: number;
    xLabel?: string;
    yLabel?: string;
    color?: string;
    showGrid?: boolean;
  }

  let {
    data,
    height = 300,
    xLabel,
    yLabel,
    color = 'primary',
    showGrid = true
  }: Props = $props();

  const colorClass = `fill-${color}/20`;
  const lineClass = `stroke-${color} stroke-2`;
</script>

<div class="w-full" style="height: {height}px">
  <Chart
    {data}
    x="date"
    xScale={scaleTime()}
    y="value"
    yScale={scaleLinear()}
    yNice
    padding={{ top: 20, bottom: 40, left: 50, right: 20 }}
  >
    <Svg>
      {#if showGrid}
        <Axis placement="left" grid={{ class: 'stroke-surface-300' }} />
        <Axis placement="bottom" />
      {:else}
        <Axis placement="left" />
        <Axis placement="bottom" />
      {/if}

      <Area class={colorClass} line={{ class: lineClass }} />
      <Highlight points lines />
    </Svg>

    <Tooltip header={(d) => format(d.date, 'MMM d, yyyy')}>
      <TooltipItem label="Value" value={(d) => d.value.toLocaleString()} />
    </Tooltip>
  </Chart>
</div>
```

### 5.3 Bar Chart Component

```svelte
<!-- services/webapp/src/lib/components/charts/BarChart.svelte -->
<script lang="ts">
  import { Chart, Svg, Bars, Axis, Tooltip, TooltipItem } from 'layerchart';
  import { scaleBand, scaleLinear } from 'd3-scale';

  interface DataPoint {
    label: string;
    value: number;
  }

  interface Props {
    data: DataPoint[];
    height?: number;
    horizontal?: boolean;
    color?: string;
  }

  let {
    data,
    height = 300,
    horizontal = false,
    color = 'primary'
  }: Props = $props();
</script>

<div class="w-full" style="height: {height}px">
  <Chart
    {data}
    x="label"
    xScale={scaleBand().padding(0.2)}
    y="value"
    yScale={scaleLinear()}
    yNice
    padding={{ top: 20, bottom: 40, left: 50, right: 20 }}
  >
    <Svg>
      <Axis placement="left" />
      <Axis placement="bottom" />
      <Bars class="fill-primary hover:fill-primary/80 transition-colors" />
    </Svg>

    <Tooltip>
      <TooltipItem label={(d) => d.label} value={(d) => d.value.toLocaleString()} />
    </Tooltip>
  </Chart>
</div>
```

### 5.4 Pie/Donut Chart Component

```svelte
<!-- services/webapp/src/lib/components/charts/PieChart.svelte -->
<script lang="ts">
  import { Chart, Svg, Arc, Tooltip, TooltipItem } from 'layerchart';
  import { pie, arc } from 'd3-shape';
  import { scaleOrdinal } from 'd3-scale';

  interface DataPoint {
    label: string;
    value: number;
    color?: string;
  }

  interface Props {
    data: DataPoint[];
    size?: number;
    donut?: boolean;
    showLabels?: boolean;
  }

  let {
    data,
    size = 200,
    donut = false,
    showLabels = true
  }: Props = $props();

  const colors = [
    'rgb(var(--color-chart-1))',
    'rgb(var(--color-chart-2))',
    'rgb(var(--color-chart-3))',
    'rgb(var(--color-chart-4))',
    'rgb(var(--color-chart-5))',
    'rgb(var(--color-chart-6))'
  ];

  const colorScale = scaleOrdinal<string>().domain(data.map(d => d.label)).range(colors);

  const pieGenerator = pie<DataPoint>().value(d => d.value);
  const pieData = pieGenerator(data);

  const outerRadius = size / 2 - 10;
  const innerRadius = donut ? outerRadius * 0.6 : 0;

  const arcGenerator = arc<any>()
    .innerRadius(innerRadius)
    .outerRadius(outerRadius);
</script>

<div class="flex flex-col items-center">
  <svg width={size} height={size}>
    <g transform="translate({size / 2}, {size / 2})">
      {#each pieData as slice}
        <path
          d={arcGenerator(slice)}
          fill={slice.data.color || colorScale(slice.data.label)}
          class="hover:opacity-80 transition-opacity cursor-pointer"
        />
      {/each}
    </g>
  </svg>

  {#if showLabels}
    <div class="flex flex-wrap justify-center gap-4 mt-4">
      {#each data as item, i}
        <div class="flex items-center gap-2 text-sm">
          <div
            class="w-3 h-3 rounded-full"
            style="background-color: {item.color || colors[i % colors.length]}"
          ></div>
          <span class="text-muted">{item.label}</span>
          <span class="font-medium text-on-surface">{item.value}</span>
        </div>
      {/each}
    </div>
  {/if}
</div>
```

---

## Phase 6: Dashboard Page Implementation

### 6.1 Dashboard Page Structure

```svelte
<!-- services/webapp/src/routes/dashboard/+page.svelte -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { FileText, Database, Cpu, HardDrive, Activity, CheckCircle, XCircle } from 'lucide-svelte';
  import StatCard from '$lib/components/charts/StatCard.svelte';
  import AreaChart from '$lib/components/charts/AreaChart.svelte';
  import BarChart from '$lib/components/charts/BarChart.svelte';
  import PieChart from '$lib/components/charts/PieChart.svelte';

  interface SystemStats {
    total_documents: number;
    total_embeddings: number;
    total_chunks: number;
    total_size_bytes: number;
    hybrid_search_enabled: boolean;
    contextual_retrieval_enabled: boolean;
    reranker_enabled: boolean;
    retrieval_top_k: number;
    rrf_k: number;
    services: Record<string, string>;
  }

  let stats = $state<SystemStats | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  // Mock query history data (would come from API)
  let queryHistory = $state([
    { date: new Date('2024-01-01'), value: 12 },
    { date: new Date('2024-01-02'), value: 19 },
    { date: new Date('2024-01-03'), value: 15 },
    { date: new Date('2024-01-04'), value: 25 },
    { date: new Date('2024-01-05'), value: 32 },
    { date: new Date('2024-01-06'), value: 28 },
    { date: new Date('2024-01-07'), value: 35 }
  ]);

  // Document types distribution
  let documentTypes = $state([
    { label: 'PDF', value: 45 },
    { label: 'DOCX', value: 20 },
    { label: 'TXT', value: 15 },
    { label: 'HTML', value: 12 },
    { label: 'Other', value: 8 }
  ]);

  onMount(async () => {
    try {
      const res = await fetch('/api/stats');
      if (!res.ok) throw new Error('Failed to fetch stats');
      stats = await res.json();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Unknown error';
    } finally {
      loading = false;
    }
  });

  function formatBytes(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  }
</script>

<svelte:head>
  <title>Dashboard - RAG System</title>
</svelte:head>

<div class="p-6 max-w-7xl mx-auto">
  <h1 class="text-2xl font-semibold text-on-surface mb-6">Dashboard</h1>

  {#if loading}
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {#each Array(4) as _}
        <div class="bg-surface-raised rounded-lg p-4 animate-pulse h-32"></div>
      {/each}
    </div>
  {:else if error}
    <div class="bg-red-500/10 border border-red-500/20 rounded-lg p-4 text-red-500">
      Error: {error}
    </div>
  {:else if stats}
    <!-- Service Status -->
    <div class="flex gap-2 mb-6">
      {#each Object.entries(stats.services) as [name, status]}
        <div class="flex items-center gap-2 px-3 py-1.5 bg-surface-raised rounded-full text-sm">
          {#if status === 'healthy'}
            <CheckCircle class="w-4 h-4 text-green-500" />
          {:else}
            <XCircle class="w-4 h-4 text-red-500" />
          {/if}
          <span class="capitalize text-on-surface">{name}</span>
        </div>
      {/each}
    </div>

    <!-- Stats Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <StatCard
        title="Documents"
        value={stats.total_documents}
        icon={FileText}
        sparklineData={queryHistory}
      />
      <StatCard
        title="Embeddings"
        value={stats.total_embeddings.toLocaleString()}
        icon={Database}
        trend={5.2}
      />
      <StatCard
        title="Chunks"
        value={stats.total_chunks.toLocaleString()}
        icon={Cpu}
      />
      <StatCard
        title="Storage"
        value={formatBytes(stats.total_size_bytes)}
        icon={HardDrive}
      />
    </div>

    <!-- Charts Row -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
      <!-- Query History Chart -->
      <div class="bg-surface-raised rounded-lg p-4 border border-default">
        <h3 class="text-lg font-medium text-on-surface mb-4">Query Activity</h3>
        <AreaChart data={queryHistory} height={250} />
      </div>

      <!-- Document Types Chart -->
      <div class="bg-surface-raised rounded-lg p-4 border border-default">
        <h3 class="text-lg font-medium text-on-surface mb-4">Document Types</h3>
        <div class="flex justify-center">
          <PieChart data={documentTypes} donut />
        </div>
      </div>
    </div>

    <!-- RAG Configuration -->
    <div class="bg-surface-raised rounded-lg p-4 border border-default">
      <h3 class="text-lg font-medium text-on-surface mb-4">RAG Configuration</h3>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="flex items-center justify-between p-3 bg-surface rounded-lg">
          <span class="text-sm text-muted">Hybrid Search</span>
          <span class="text-sm font-medium {stats.hybrid_search_enabled ? 'text-green-500' : 'text-red-500'}">
            {stats.hybrid_search_enabled ? 'On' : 'Off'}
          </span>
        </div>
        <div class="flex items-center justify-between p-3 bg-surface rounded-lg">
          <span class="text-sm text-muted">Contextual Retrieval</span>
          <span class="text-sm font-medium {stats.contextual_retrieval_enabled ? 'text-green-500' : 'text-red-500'}">
            {stats.contextual_retrieval_enabled ? 'On' : 'Off'}
          </span>
        </div>
        <div class="flex items-center justify-between p-3 bg-surface rounded-lg">
          <span class="text-sm text-muted">Reranker</span>
          <span class="text-sm font-medium {stats.reranker_enabled ? 'text-green-500' : 'text-red-500'}">
            {stats.reranker_enabled ? 'On' : 'Off'}
          </span>
        </div>
        <div class="flex items-center justify-between p-3 bg-surface rounded-lg">
          <span class="text-sm text-muted">Top-K</span>
          <span class="text-sm font-medium text-on-surface">{stats.retrieval_top_k}</span>
        </div>
      </div>
    </div>
  {/if}
</div>
```

---

## Phase 7: File Structure After Migration

```
services/webapp/src/
├── app.css                                    # Tailwind 4 + svelte-ux + themes
├── app.html                                   # Flash prevention script
├── lib/
│   ├── components/
│   │   ├── ui/                                # Svelte-ux wrappers
│   │   │   ├── Button.svelte
│   │   │   ├── Input.svelte
│   │   │   ├── Dialog.svelte
│   │   │   └── index.ts
│   │   ├── charts/                            # LayerChart wrappers
│   │   │   ├── StatCard.svelte
│   │   │   ├── AreaChart.svelte
│   │   │   ├── BarChart.svelte
│   │   │   ├── PieChart.svelte
│   │   │   ├── LineChart.svelte
│   │   │   └── index.ts
│   │   ├── layout/
│   │   │   ├── Sidebar.svelte                 # Keep existing
│   │   │   ├── SidebarItem.svelte             # Keep existing
│   │   │   └── ThemeToggle.svelte             # Keep existing
│   │   ├── chat/
│   │   │   ├── ChatMessage.svelte             # Keep existing
│   │   │   └── Citation.svelte                # Keep existing
│   │   ├── feedback/
│   │   │   ├── Toast.svelte                   # Keep existing
│   │   │   ├── ToastContainer.svelte          # Keep existing
│   │   │   ├── ConfirmDialog.svelte           # Keep existing
│   │   │   └── LoadingSkeleton.svelte         # Keep existing
│   │   ├── ChatInterface.svelte               # Refactor to use ui components
│   │   ├── DocumentTable.svelte               # Refactor to use ui components
│   │   └── FileUpload.svelte                  # Refactor to use ui components
│   ├── stores/
│   │   ├── theme.svelte.ts                    # Updated for svelte-ux
│   │   ├── sidebar.svelte.ts                  # Keep existing
│   │   ├── toast.svelte.ts                    # Keep existing
│   │   └── chat.ts                            # Keep existing
│   └── utils/
│       ├── api.ts                             # Keep existing
│       └── session.ts                         # Keep existing
└── routes/
    ├── +layout.svelte                         # Add svelte-ux initialization
    ├── +page.svelte                           # Redirect to /documents
    ├── documents/+page.svelte                 # Document management
    ├── chat/+page.svelte                      # Chat interface
    ├── dashboard/+page.svelte                 # NEW: Stats dashboard with charts
    └── api/
        └── stats/+server.ts                   # Proxy to backend /stats
```

---

## Phase 8: Migration Checklist

### 8.1 Pre-Migration
- [ ] Create feature branch
- [ ] Backup current working state
- [ ] Review all existing components

### 8.2 Core Setup
- [ ] Install svelte-ux, layerchart, @layerstack/tailwind
- [ ] Update app.css with new configuration
- [ ] Update +layout.svelte with svelte-ux initialization
- [ ] Test dark/light theme switching

### 8.3 Component Migration
- [ ] Create ui/ wrapper components (Button, Input, Dialog)
- [ ] Create charts/ wrapper components (StatCard, AreaChart, etc.)
- [ ] Update existing components to use new patterns
- [ ] Test all components in both themes

### 8.4 Dashboard Implementation
- [ ] Add /stats endpoint to RAG server
- [ ] Create dashboard page with charts
- [ ] Test with real data

### 8.5 Testing & Polish
- [ ] Test all pages in light mode
- [ ] Test all pages in dark mode
- [ ] Test responsive layouts
- [ ] Performance check (bundle size)
- [ ] Accessibility audit

---

## Phase 9: Future Enhancements

Once the foundation is in place, these features become easy to add:

1. **Advanced Dashboard**
   - Query latency histogram
   - Document upload timeline
   - Real-time service metrics
   - Error rate charts

2. **Document Analytics**
   - Chunk size distribution
   - Document processing times
   - Embedding dimensions visualization

3. **Chat Analytics**
   - Session duration charts
   - Query frequency heatmap
   - Citation usage statistics

4. **Admin Features**
   - Batch operations UI
   - Configuration editor
   - Log viewer

---

## Dependencies Summary

```json
{
  "dependencies": {
    "svelte-ux": "^1.0.0",
    "layerchart": "^2.0.0",
    "lucide-svelte": "^0.556.0"
  },
  "devDependencies": {
    "@layerstack/tailwind": "^1.0.0",
    "tailwindcss": "^4.0.0"
  }
}
```

---

## References

- [Svelte UX Documentation](https://next.svelte-ux.techniq.dev)
- [LayerChart Documentation](https://layerchart.com)
- [Tailwind CSS v4 Upgrade Guide](https://tailwindcss.com/docs/upgrade-guide)
- [@layerstack/tailwind](https://github.com/techniq/layerstack)
