<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { sidebarOpen, toggleSidebar } from '$lib/stores/sidebar';
  import {
    fetchChatSessions,
    createNewSession,
    deleteSession,
    archiveSession,
    unarchiveSession,
    getChatHistory
  } from '$lib/api';
  import type { SessionMetadata } from '$lib/api';
  import { onMount } from 'svelte';

  let activeSessions: SessionMetadata[] = $state([]);
  let archivedSessions: SessionMetadata[] = $state([]);
  let loading = $state(true);
  let error: string | null = $state(null);
  let showArchived = $state(true);

  onMount(() => {
    loadSessions();
  });

  async function loadSessions() {
    loading = true;
    error = null;
    try {
      const sessions = await fetchChatSessions(true);
      activeSessions = sessions.filter(s => !s.is_archived);
      archivedSessions = sessions.filter(s => s.is_archived);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sessions';
      console.error('Failed to load sessions:', err);
    } finally {
      loading = false;
    }
  }

  async function handleNewSession() {
    try {
      const newSession = await createNewSession();
      await goto(`/chat?session_id=${newSession.session_id}`);
      await loadSessions();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to create session';
      console.error('Failed to create session:', err);
    }
  }

  async function handleDeleteSession(sessionId: string) {
    if (!confirm('Are you sure you want to delete this session? This cannot be undone.')) {
      return;
    }

    try {
      await deleteSession(sessionId);
      await loadSessions();

      if ($page.url.searchParams.get('session_id') === sessionId) {
        await goto('/chat');
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to delete session';
      console.error('Failed to delete session:', err);
    }
  }

  async function handleArchiveSession(sessionId: string) {
    try {
      await archiveSession(sessionId);
      await loadSessions();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to archive session';
      console.error('Failed to archive session:', err);
    }
  }

  async function handleUnarchiveSession(sessionId: string) {
    try {
      await unarchiveSession(sessionId);
      await loadSessions();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to unarchive session';
      console.error('Failed to unarchive session:', err);
    }
  }

  async function handleExportSession(sessionId: string, title: string) {
    try {
      const history = await getChatHistory(sessionId);
      if (history.messages.length === 0) {
        error = 'No messages to export';
        return;
      }

      const text = history.messages
        .map(m => `${m.role === 'user' ? 'User' : 'Assistant'}:\n${m.content}`)
        .join('\n\n---\n\n');

      const blob = new Blob([text], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${title || 'chat'}-${sessionId.slice(0, 8)}.txt`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to export session';
      console.error('Failed to export session:', err);
    }
  }

  function handleSessionClick(sessionId: string) {
    goto(`/chat?session_id=${sessionId}`);
  }

  function formatTimestamp(timestamp: string): string {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;

    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function isCurrentSession(sessionId: string): boolean {
    return $page.url.searchParams.get('session_id') === sessionId;
  }
</script>

<aside
  class="sidebar-container bg-base-200 border-r border-base-300 flex flex-col h-screen"
  class:expanded={$sidebarOpen}
>
  <!-- Toggle button - always visible -->
  <div class="p-3 flex" class:justify-end={$sidebarOpen} class:justify-center={!$sidebarOpen}>
    <button
      class="btn btn-ghost btn-square btn-sm"
      onclick={toggleSidebar}
      aria-label={$sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
      title={$sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <rect x="3" y="3" width="7" height="18" rx="1" />
        <rect x="14" y="3" width="7" height="18" rx="1" />
      </svg>
    </button>
  </div>

  <!-- Expanded content -->
  {#if $sidebarOpen}
    <div class="flex-1 flex flex-col overflow-hidden sidebar-content">
      <!-- New Chat Button -->
      <div class="px-3 pb-4">
        <button
          class="flex items-center gap-3 w-full p-2 rounded-lg hover:bg-base-300 transition-colors text-base-content"
          onclick={handleNewSession}
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h6" />
          </svg>
          <span class="text-sm">New chat</span>
        </button>
      </div>

      <!-- Error Display -->
      {#if error}
        <div class="alert alert-error mx-3 mb-3 text-sm py-2">
          <span>{error}</span>
        </div>
      {/if}

      <!-- Sessions List -->
      <div class="flex-1 overflow-y-auto px-3">
        {#if loading}
          <div class="flex items-center justify-center py-8">
            <span class="loading loading-spinner loading-md"></span>
          </div>
        {:else}
          <!-- Recent (Active) Sessions -->
          <div class="mb-4">
            <div class="flex items-center justify-between mb-2">
              <h3 class="text-xs font-semibold text-base-content/60 uppercase tracking-wider">Recent</h3>
              <span class="text-xs text-base-content/40">{activeSessions.length}</span>
            </div>

            {#if activeSessions.length === 0}
              <p class="text-xs text-base-content/50 text-center py-3">No active chats</p>
            {:else}
              <div class="space-y-0.5">
                {#each activeSessions as session (session.session_id)}
                  <div
                    class="has-tooltip group relative py-1.5 px-2 rounded-lg hover:bg-base-300 cursor-pointer transition-colors {isCurrentSession(session.session_id) ? 'bg-primary/10 border border-primary/30' : ''}"
                    onclick={() => handleSessionClick(session.session_id)}
                    onkeydown={(e) => e.key === 'Enter' && handleSessionClick(session.session_id)}
                    role="button"
                    tabindex="0"
                    data-tooltip={formatTimestamp(session.updated_at)}
                  >
                    <div class="flex items-center justify-between gap-1">
                      <p class="flex-1 min-w-0 text-sm truncate">
                        {session.title || 'Untitled Chat'}
                      </p>

                      <div class="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          class="has-tooltip btn btn-ghost btn-xs btn-square"
                          onclick={(e) => { e.stopPropagation(); handleArchiveSession(session.session_id); }}
                          aria-label="Archive session"
                          data-tooltip="Archive"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                          </svg>
                        </button>
                        <button
                          class="has-tooltip btn btn-ghost btn-xs btn-square text-error hover:bg-error/20"
                          onclick={(e) => { e.stopPropagation(); handleDeleteSession(session.session_id); }}
                          aria-label="Delete session"
                          data-tooltip="Delete"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                        <button
                          class="has-tooltip btn btn-ghost btn-xs btn-square"
                          onclick={(e) => { e.stopPropagation(); handleExportSession(session.session_id, session.title); }}
                          aria-label="Export chat"
                          data-tooltip="Export"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                          </svg>
                        </button>
                      </div>
                    </div>
                  </div>
                {/each}
              </div>
            {/if}
          </div>

          <!-- Archived Sessions -->
          <div class="border-t border-base-300 pt-3">
            <button
              class="w-full flex items-center justify-between text-xs font-semibold text-base-content/60 uppercase tracking-wider hover:text-base-content mb-2"
              onclick={() => showArchived = !showArchived}
            >
              <span>Archived</span>
              <div class="flex items-center gap-1">
                <span class="text-xs text-base-content/40 normal-case">{archivedSessions.length}</span>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  class="h-3 w-3 transition-transform {showArchived ? 'rotate-180' : ''}"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                </svg>
              </div>
            </button>

            {#if showArchived}
              {#if archivedSessions.length === 0}
                <p class="text-xs text-base-content/50 text-center py-3">No archived chats</p>
              {:else}
                <div class="space-y-0.5">
                  {#each archivedSessions as session (session.session_id)}
                    <div
                      class="has-tooltip group relative py-1.5 px-2 rounded-lg hover:bg-base-300 cursor-pointer transition-colors"
                      onclick={() => handleSessionClick(session.session_id)}
                      onkeydown={(e) => e.key === 'Enter' && handleSessionClick(session.session_id)}
                      role="button"
                      tabindex="0"
                      data-tooltip={formatTimestamp(session.updated_at)}
                    >
                      <div class="flex items-center justify-between gap-1">
                        <p class="flex-1 min-w-0 text-sm truncate opacity-70">
                          {session.title || 'Untitled Chat'}
                        </p>

                        <div class="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            class="has-tooltip btn btn-ghost btn-xs btn-square"
                            onclick={(e) => { e.stopPropagation(); handleUnarchiveSession(session.session_id); }}
                            aria-label="Unarchive session"
                            data-tooltip="Unarchive"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                            </svg>
                          </button>
                          <button
                            class="has-tooltip btn btn-ghost btn-xs btn-square text-error hover:bg-error/20"
                            onclick={(e) => { e.stopPropagation(); handleDeleteSession(session.session_id); }}
                            aria-label="Delete session"
                            data-tooltip="Delete"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                          </button>
                          <button
                            class="has-tooltip btn btn-ghost btn-xs btn-square"
                            onclick={(e) => { e.stopPropagation(); handleExportSession(session.session_id, session.title); }}
                            aria-label="Export chat"
                            data-tooltip="Export"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                            </svg>
                          </button>
                        </div>
                      </div>
                    </div>
                  {/each}
                </div>
              {/if}
            {/if}
          </div>
        {/if}
      </div>
    </div>
  {/if}
</aside>

<style>
  .sidebar-container {
    width: 48px;
    min-width: 48px;
    transition: width 0.3s ease, min-width 0.3s ease;
    overflow: hidden;
  }

  .sidebar-container.expanded {
    width: 280px;
    min-width: 280px;
  }

  .sidebar-content {
    opacity: 0;
    animation: fadeIn 0.2s ease 0.1s forwards;
  }

  @keyframes fadeIn {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }
</style>
