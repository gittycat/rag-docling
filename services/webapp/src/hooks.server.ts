import type { Handle } from '@sveltejs/kit';
import { isValidTheme } from '$lib/themes';
import { env } from '$env/dynamic/private';

const RAG_SERVER_URL = env.RAG_SERVER_URL || 'http://localhost:8001';

export const handle: Handle = async ({ event, resolve }) => {
	// Proxy /api/* requests to RAG server (production mode)
	if (event.url.pathname.startsWith('/api/')) {
		const targetPath = event.url.pathname.replace(/^\/api/, '');
		const targetUrl = `${RAG_SERVER_URL}${targetPath}${event.url.search}`;

		const headers = new Headers(event.request.headers);
		headers.delete('host');

		const response = await fetch(targetUrl, {
			method: event.request.method,
			headers,
			body: event.request.method !== 'GET' && event.request.method !== 'HEAD'
				? event.request.body
				: undefined,
			// @ts-expect-error - duplex is needed for streaming request bodies
			duplex: 'half'
		});

		return new Response(response.body, {
			status: response.status,
			statusText: response.statusText,
			headers: response.headers
		});
	}

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
