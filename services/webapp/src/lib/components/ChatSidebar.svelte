<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { sidebarOpen, closeSidebar } from '$lib/stores/sidebar';
  import {
    fetchChatSessions,
    createNewSession,
    deleteSession,
    archiveSession,
    unarchiveSession
  } from '$lib/api';
  import type { ChatSessionMetadata } from '$lib/api';
  import { onMount } from 'svelte';

  let activeSessions: ChatSessionMetadata[] = [];
  let archivedSessions: ChatSessionMetadata[] = [];
  let loading = true;
  let error: string | null = null;
  let showArchived = false;

  onMount(() => {
    loadSessions();
  });

  async function loadSessions() {
    loading = true;
    error = null;
    try {
      const sessions = await fetchChatSessions();
      activeSessions = sessions.filter(s => !s.archived);
      archivedSessions = sessions.filter(s => s.archived);
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
      closeSidebar();
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

      // If we deleted the current session, redirect to temporary chat
      if ($page.url.searchParams.get('session_id') === sessionId) {
        closeSidebar();
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

  function handleSessionClick(sessionId: string) {
    closeSidebar();
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

  function handleOverlayClick() {
    closeSidebar();
  }
</script>

{#if $sidebarOpen}
  <div class="fixed inset-0 z-50">
    <!-- Overlay -->
    <div
      class="absolute inset-0 bg-black bg-opacity-50 transition-opacity"
      on:click={handleOverlayClick}
      on:keydown={(e) => e.key === 'Escape' && closeSidebar()}
      role="button"
      tabindex="0"
    ></div>

    <!-- Sidebar -->
    <div class="absolute inset-y-0 left-0 w-80 bg-base-200 shadow-xl flex flex-col animate-slide-in">
      <!-- Header -->
      <div class="p-4 border-b border-base-300 flex items-center justify-between">
        <h2 class="text-lg font-semibold">Chat Sessions</h2>
        <button
          class="btn btn-ghost btn-sm btn-circle"
          on:click={closeSidebar}
          aria-label="Close sidebar"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- New Session Button -->
      <div class="p-4 border-b border-base-300">
        <button
          class="btn btn-primary btn-block"
          on:click={handleNewSession}
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
          </svg>
          New Chat
        </button>
      </div>

      <!-- Error Display -->
      {#if error}
        <div class="alert alert-error m-4">
          <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{error}</span>
        </div>
      {/if}

      <!-- Sessions List -->
      <div class="flex-1 overflow-y-auto">
        {#if loading}
          <div class="flex items-center justify-center p-8">
            <span class="loading loading-spinner loading-lg"></span>
          </div>
        {:else}
          <!-- Active Sessions -->
          <div class="p-4">
            <div class="flex items-center justify-between mb-2">
              <h3 class="text-sm font-semibold text-base-content/70">Active</h3>
              <span class="text-xs text-base-content/50">{activeSessions.length}</span>
            </div>

            {#if activeSessions.length === 0}
              <p class="text-sm text-base-content/50 text-center py-4">No active sessions</p>
            {:else}
              <div class="space-y-2">
                {#each activeSessions as session}
                  <div
                    class="group relative p-3 rounded-lg hover:bg-base-300 cursor-pointer transition-colors {isCurrentSession(session.session_id) ? 'bg-primary/10 border border-primary' : 'border border-transparent'}"
                    on:click={() => handleSessionClick(session.session_id)}
                    on:keydown={(e) => e.key === 'Enter' && handleSessionClick(session.session_id)}
                    role="button"
                    tabindex="0"
                  >
                    <div class="flex items-start justify-between gap-2">
                      <div class="flex-1 min-w-0">
                        <p class="text-sm font-medium truncate">
                          {session.title || 'Untitled Chat'}
                        </p>
                        <p class="text-xs text-base-content/50 mt-1">
                          {formatTimestamp(session.last_updated)}
                        </p>
                      </div>

                      <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          class="btn btn-ghost btn-xs btn-square"
                          on:click|stopPropagation={() => handleArchiveSession(session.session_id)}
                          aria-label="Archive session"
                          title="Archive"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                          </svg>
                        </button>
                        <button
                          class="btn btn-ghost btn-xs btn-square text-error hover:bg-error/20"
                          on:click|stopPropagation={() => handleDeleteSession(session.session_id)}
                          aria-label="Delete session"
                          title="Delete"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
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
          <div class="p-4 border-t border-base-300">
            <button
              class="w-full flex items-center justify-between text-sm font-semibold text-base-content/70 hover:text-base-content mb-2"
              on:click={() => showArchived = !showArchived}
            >
              <span>Archived</span>
              <div class="flex items-center gap-2">
                <span class="text-xs text-base-content/50">{archivedSessions.length}</span>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  class="h-4 w-4 transition-transform {showArchived ? 'rotate-180' : ''}"
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
                <p class="text-sm text-base-content/50 text-center py-4">No archived sessions</p>
              {:else}
                <div class="space-y-2">
                  {#each archivedSessions as session}
                    <div
                      class="group relative p-3 rounded-lg hover:bg-base-300 cursor-pointer transition-colors border border-transparent"
                      on:click={() => handleSessionClick(session.session_id)}
                      on:keydown={(e) => e.key === 'Enter' && handleSessionClick(session.session_id)}
                      role="button"
                      tabindex="0"
                    >
                      <div class="flex items-start justify-between gap-2">
                        <div class="flex-1 min-w-0">
                          <p class="text-sm font-medium truncate opacity-70">
                            {session.title || 'Untitled Chat'}
                          </p>
                          <p class="text-xs text-base-content/50 mt-1">
                            {formatTimestamp(session.last_updated)}
                          </p>
                        </div>

                        <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            class="btn btn-ghost btn-xs btn-square"
                            on:click|stopPropagation={() => handleUnarchiveSession(session.session_id)}
                            aria-label="Unarchive session"
                            title="Unarchive"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                            </svg>
                          </button>
                          <button
                            class="btn btn-ghost btn-xs btn-square text-error hover:bg-error/20"
                            on:click|stopPropagation={() => handleDeleteSession(session.session_id)}
                            aria-label="Delete session"
                            title="Delete"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
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
  </div>
{/if}

<style>
  @keyframes slide-in {
    from {
      transform: translateX(-100%);
    }
    to {
      transform: translateX(0);
    }
  }

  .animate-slide-in {
    animation: slide-in 0.3s ease-out;
  }
</style>
