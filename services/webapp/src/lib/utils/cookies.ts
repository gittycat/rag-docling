import { browser } from '$app/environment';

export const COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // 1 year

/**
 * Read a cookie value by name
 */
export function getCookie(name: string): string | null {
	if (!browser) return null;
	const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
	return match ? match[2] : null;
}

/**
 * Set a cookie with the given name and value
 */
export function setCookie(name: string, value: string): void {
	if (!browser) return;
	document.cookie = `${name}=${value}; max-age=${COOKIE_MAX_AGE}; path=/; SameSite=Lax`;
}

/**
 * Get initial boolean state from cookie
 */
export function getCookieBool(cookieName: string, defaultValue: boolean): boolean {
	const cookieValue = getCookie(cookieName);
	if (cookieValue === null) return defaultValue;
	return cookieValue === 'true';
}

/**
 * Get initial number state from cookie
 */
export function getCookieNumber(cookieName: string, defaultValue: number): number {
	const cookieValue = getCookie(cookieName);
	if (cookieValue === null) return defaultValue;
	const parsed = parseFloat(cookieValue);
	return isNaN(parsed) ? defaultValue : parsed;
}
