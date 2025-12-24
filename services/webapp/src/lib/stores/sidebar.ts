import { writable } from 'svelte/store';

/**
 * Global sidebar state (open/closed)
 */
export const sidebarOpen = writable(false);

export function toggleSidebar() {
	sidebarOpen.update((open) => !open);
}

export function closeSidebar() {
	sidebarOpen.set(false);
}

export function openSidebar() {
	sidebarOpen.set(true);
}
