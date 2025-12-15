import type { Handle } from '@sveltejs/kit';
import { themes, isValidTheme } from '$lib/themes';

export const handle: Handle = async ({ event, resolve }) => {
	const theme = event.cookies.get('theme');

	// If no valid theme cookie, render with default (let CSS handle it)
	if (!theme || !isValidTheme(theme)) {
		return await resolve(event);
	}

	// Inject theme into HTML before sending to client (prevents FOUC)
	return await resolve(event, {
		transformPageChunk: ({ html }) => {
			return html.replace('data-theme=""', `data-theme="${theme}"`);
		}
	});
};
