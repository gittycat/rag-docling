# Create Svelte 5 + Tailwind CSS 4 + DaisyUI Webapp

## CLI Commands

```bash
# 1. Create project (from /services directory)
cd /Users/bernard/dev/code/rag/rag-docling/services
npx -y sv create webapp --template minimal --types ts --add tailwindcss
cd webapp

# 2. Install DaisyUI 5
npm install -D daisyui@latest

# 3. Install Tailwind Vite plugin (required for Tailwind v4)
npm install -D @tailwindcss/vite
```

---

## Configuration Files

### 1. `vite.config.ts`

**CRITICAL:** The `@tailwindcss/vite` plugin must be placed BEFORE `sveltekit()`.

```typescript
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [
    tailwindcss(),
    sveltekit()
  ],
  server: {
    host: '0.0.0.0',
    port: 5173
  }
});
```

### 2. `src/app.css`

```css
@import "tailwindcss";
@plugin "daisyui" {
  themes: light --default, dark --prefersdark;
}
```

---

## Route Files to Create

### 3. `src/routes/+layout.svelte`

```svelte
<script lang="ts">
  let { children } = $props();
</script>

<div class="min-h-screen bg-base-100">
  <div class="navbar bg-base-200 shadow-lg">
    <div class="flex-1">
      <a href="/" class="btn btn-ghost text-xl">RAG App</a>
    </div>
    <div class="flex-none">
      <ul class="menu menu-horizontal px-1">
        <li><a href="/chat">Chat</a></li>
        <li><a href="/documents">Documents</a></li>
        <li><a href="/dashboard">Dashboard</a></li>
      </ul>
    </div>
  </div>

  <main class="container mx-auto p-4">
    {@render children()}
  </main>
</div>

<style>
  @import '../app.css';
</style>
```

### 4. `src/routes/+page.svelte` (Home/redirect to Chat)

```svelte
<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  onMount(() => {
    goto('/chat');
  });
</script>

<div class="flex justify-center items-center h-64">
  <span class="loading loading-spinner loading-lg"></span>
</div>
```

### 5. `src/routes/chat/+page.svelte`

```svelte
<script lang="ts">
  let messages = $state([
    { role: 'assistant', content: 'Hello! How can I help you today?' }
  ]);
  let inputText = $state('');

  function sendMessage() {
    if (!inputText.trim()) return;

    messages.push({ role: 'user', content: inputText });
    // Simulate assistant response
    messages.push({ role: 'assistant', content: 'This is a placeholder response. Backend integration coming soon!' });
    inputText = '';
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }
</script>

<div class="flex flex-col h-[calc(100vh-140px)]">
  <div class="flex-1 overflow-y-auto p-4 space-y-4">
    {#each messages as message, index (index)}
      <div class="chat {message.role === 'user' ? 'chat-end' : 'chat-start'}">
        <div class="chat-image avatar placeholder">
          <div class="bg-neutral text-neutral-content w-10 rounded-full">
            <span>{message.role === 'user' ? 'U' : 'AI'}</span>
          </div>
        </div>
        <div class="chat-header">
          {message.role === 'user' ? 'You' : 'Assistant'}
        </div>
        <div class="chat-bubble {message.role === 'user' ? 'chat-bubble-primary' : 'chat-bubble-secondary'}">
          {message.content}
        </div>
      </div>
    {/each}
  </div>

  <div class="p-4 bg-base-200">
    <div class="join w-full">
      <input
        type="text"
        placeholder="Type your message..."
        class="input input-bordered join-item flex-1"
        bind:value={inputText}
        onkeydown={handleKeydown}
      />
      <button class="btn btn-primary join-item" onclick={sendMessage}>
        Send
      </button>
    </div>
  </div>
</div>
```

### 6. `src/routes/documents/+page.svelte`

```svelte
<div class="flex flex-col items-center justify-center h-[calc(100vh-200px)]">
  <svg xmlns="http://www.w3.org/2000/svg" class="h-24 w-24 text-warning mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
  </svg>
  <h1 class="text-3xl font-bold mb-2">Documents</h1>
  <div class="badge badge-warning badge-lg gap-2">
    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
    </svg>
    Under Construction
  </div>
</div>
```

### 7. `src/routes/dashboard/+page.svelte`

```svelte
<div class="flex flex-col items-center justify-center h-[calc(100vh-200px)]">
  <svg xmlns="http://www.w3.org/2000/svg" class="h-24 w-24 text-info mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
  </svg>
  <h1 class="text-3xl font-bold mb-2">Dashboard</h1>
  <div class="badge badge-info badge-lg gap-2">
    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
    </svg>
    Under Construction
  </div>
</div>
```

---

## Final Directory Structure

```
services/webapp/
├── src/
│   ├── app.css
│   ├── app.html
│   └── routes/
│       ├── +layout.svelte
│       ├── +page.svelte
│       ├── chat/
│       │   └── +page.svelte
│       ├── documents/
│       │   └── +page.svelte
│       └── dashboard/
│           └── +page.svelte
├── package.json
├── svelte.config.js
├── tsconfig.json
└── vite.config.ts
```

---

## Run Development Server

```bash
cd /Users/bernard/dev/code/rag/rag-docling/services/webapp
npm run dev
```

Access at: http://localhost:5173

---

## Key Implementation Notes

1. **Tailwind v4 + DaisyUI**: Uses new CSS-based plugin syntax (`@plugin "daisyui"`) instead of old JS config
2. **Svelte 5 Runes**: Uses `$state()` for reactive state and `$props()` for component props
3. **SvelteKit Routing**: File-based routing with `+page.svelte` files
4. **DaisyUI 5 Components**: For chat interface, use `chat`, `chat-start`, `chat-end`, `chat-bubble` classes
5. **Theme Support**: Manual light/dark toggle with persistence (see below)

---

## Theme Switching Implementation

The webapp supports light (`nord`) and dark (`dim`) themes with:
- **Cookie + localStorage persistence** - survives page refresh
- **SSR injection** - prevents flash of wrong theme (FOUC)
- **DaisyUI swap component** - animated sun/moon toggle

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Hard Refresh Flow                                          │
│                                                             │
│  Browser → Server (hooks.server.ts reads cookie)            │
│         → HTML rendered with data-theme="dim"               │
│         → No flash of wrong theme                           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Toggle Click Flow                                          │
│                                                             │
│  Click → ThemeToggle.svelte persist()                       │
│       → Sets data-theme on <html>                           │
│       → Saves to localStorage + cookie                      │
│       → Next refresh reads cookie via SSR                   │
└─────────────────────────────────────────────────────────────┘
```

### Files

| File | Purpose |
|------|---------|
| `src/lib/themes.ts` | Theme constants (`nord`, `dim`) |
| `src/lib/components/ThemeToggle.svelte` | Toggle component with swap icons |
| `src/hooks.server.ts` | SSR theme injection (reads cookie, sets `data-theme`) |
| `src/app.html` | Contains `data-theme=""` placeholder |
| `src/app.css` | DaisyUI theme config |

### Key Points

1. **Don't use DaisyUI's `theme-controller` class** - it conflicts with Svelte's reactive state when syncing SSR theme
2. **Manually set `data-theme`** in the persist function instead
3. **Dual storage** (localStorage + cookie) ensures both client navigation and SSR work
4. **Cookie read happens in `hooks.server.ts`** on every server request
