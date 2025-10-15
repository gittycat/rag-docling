import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const RAG_SERVER_URL = process.env.RAG_SERVER_URL || 'http://rag-server:8001';

export const POST: RequestHandler = async ({ request }) => {
	try {
		const body = await request.json();
		const { query, session_id } = body;

		if (!query) {
			return error(400, 'Query is required');
		}

		const response = await fetch(`${RAG_SERVER_URL}/query`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json'
			},
			body: JSON.stringify({ query, session_id })
		});

		if (!response.ok) {
			const errorText = await response.text();
			return error(response.status, `RAG server error: ${errorText}`);
		}

		const data = await response.json();
		return json(data);
	} catch (err) {
		console.error('Query endpoint error:', err);
		return error(500, 'Internal server error');
	}
};
