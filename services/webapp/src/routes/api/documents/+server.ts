import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const RAG_SERVER_URL = process.env.RAG_SERVER_URL || 'http://rag-server:8001';

export const GET: RequestHandler = async () => {
	try {
		const response = await fetch(`${RAG_SERVER_URL}/documents`);

		if (!response.ok) {
			const errorText = await response.text();
			return error(response.status, `RAG server error: ${errorText}`);
		}

		const data = await response.json();
		return json(data);
	} catch (err) {
		console.error('Documents GET endpoint error:', err);
		return error(500, 'Internal server error');
	}
};
