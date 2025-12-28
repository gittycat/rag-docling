import { writable } from 'svelte/store';

/**
 * Global sidebar state (open/closed)
 */
export const sidebarOpen = writable(false);

/**
 * Counter to trigger session list refresh in sidebar
 * Increment this value to signal the sidebar to reload sessions
 */
export const sessionRefreshTrigger = writable(0);

export function toggleSidebar() {
	sidebarOpen.update((open) => !open);
}

export function closeSidebar() {
	sidebarOpen.set(false);
}

export function openSidebar() {
	sidebarOpen.set(true);
}

export function triggerSessionRefresh() {
	sessionRefreshTrigger.update((n) => n + 1);
}
