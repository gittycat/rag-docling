import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import { getCookieBool, getCookieNumber, setCookie } from '$lib/utils/cookies';

// Sidebar width constraints
export const SIDEBAR_MIN_WIDTH = 100; // Shows truncated menu items like "Up...", "Doc..."
export const SIDEBAR_DEFAULT_WIDTH = 280;
export const SIDEBAR_COLLAPSED_WIDTH = 48;

/**
 * Global sidebar state (open/closed) - persisted to cookie
 */
export const sidebarOpen = writable(browser ? getCookieBool('sidebarOpen', false) : false);

/**
 * Sidebar width when expanded - persisted to cookie
 */
export const sidebarWidth = writable(
	browser ? getCookieNumber('sidebarWidth', SIDEBAR_DEFAULT_WIDTH) : SIDEBAR_DEFAULT_WIDTH
);

/**
 * Recent section expanded/collapsed state (persisted to cookie)
 */
export const showRecentExpanded = writable(
	browser ? getCookieBool('sidebarRecentExpanded', true) : true
);

/**
 * Archived section expanded/collapsed state (persisted to cookie)
 */
export const showArchivedExpanded = writable(
	browser ? getCookieBool('sidebarArchivedExpanded', true) : true
);

// Persist all states to cookies
if (browser) {
	sidebarOpen.subscribe((value) => {
		setCookie('sidebarOpen', String(value));
	});

	sidebarWidth.subscribe((value) => {
		setCookie('sidebarWidth', String(value));
	});

	showRecentExpanded.subscribe((value) => {
		setCookie('sidebarRecentExpanded', String(value));
	});

	showArchivedExpanded.subscribe((value) => {
		setCookie('sidebarArchivedExpanded', String(value));
	});
}

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
