import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import { getCookieBool, setCookie } from '$lib/utils/cookies';

/**
 * Show help tooltips throughout the UI - persisted to cookie
 * Default: true (tooltips enabled)
 */
export const showTooltips = writable(browser ? getCookieBool('showTooltips', true) : true);

// Persist to cookie
if (browser) {
	showTooltips.subscribe((value) => {
		setCookie('showTooltips', String(value));
	});
}
