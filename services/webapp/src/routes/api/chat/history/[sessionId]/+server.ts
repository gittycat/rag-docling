import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const RAG_SERVER_URL = process.env.RAG_SERVER_URL || 'http://rag-server:8001';

export const GET: RequestHandler = async ({ params }) => {
	try {
		const { sessionId } = params;

		if (!sessionId) {
			return error(400, 'Session ID is required');
		}

		const response = await fetch(`${RAG_SERVER_URL}/chat/history/${sessionId}`);

		if (!response.ok) {
			const errorText = await response.text();
			return error(response.status, `RAG server error: ${errorText}`);
		}

		const data = await response.json();
		return json(data);
	} catch (err) {
		console.error('Chat history endpoint error:', err);
		return error(500, 'Internal server error');
	}
};
