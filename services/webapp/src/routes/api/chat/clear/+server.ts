import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const RAG_SERVER_URL = process.env.RAG_SERVER_URL || 'http://rag-server:8001';

export const POST: RequestHandler = async ({ request }) => {
	try {
		const body = await request.json();
		const { session_id } = body;

		if (!session_id) {
			return error(400, 'Session ID is required');
		}

		const response = await fetch(`${RAG_SERVER_URL}/chat/clear`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json'
			},
			body: JSON.stringify({ session_id })
		});

		if (!response.ok) {
			const errorText = await response.text();
			return error(response.status, `RAG server error: ${errorText}`);
		}

		return json({ success: true });
	} catch (err) {
		console.error('Chat clear endpoint error:', err);
		return error(500, 'Internal server error');
	}
};
