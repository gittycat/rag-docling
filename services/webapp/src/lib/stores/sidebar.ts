import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // 1 year

/**
 * Read a cookie value by name
 */
function getCookie(name: string): string | null {
	if (!browser) return null;
	const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
	return match ? match[2] : null;
}

/**
 * Set a cookie with the given name and value
 */
function setCookie(name: string, value: string): void {
	if (!browser) return;
	document.cookie = `${name}=${value}; max-age=${COOKIE_MAX_AGE}; path=/; SameSite=Lax`;
}

/**
 * Initialize sidebar section states from cookies
 */
function getInitialSectionState(cookieName: string, defaultValue: boolean): boolean {
	const cookieValue = getCookie(cookieName);
	if (cookieValue === null) return defaultValue;
	return cookieValue === 'true';
}

/**
 * Global sidebar state (open/closed)
 */
export const sidebarOpen = writable(false);

/**
 * Recent section expanded/collapsed state (persisted to cookie)
 */
export const showRecentExpanded = writable(
	browser ? getInitialSectionState('sidebarRecentExpanded', true) : true
);

/**
 * Archived section expanded/collapsed state (persisted to cookie)
 */
export const showArchivedExpanded = writable(
	browser ? getInitialSectionState('sidebarArchivedExpanded', true) : true
);

// Subscribe to store changes and persist to cookies
if (browser) {
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
