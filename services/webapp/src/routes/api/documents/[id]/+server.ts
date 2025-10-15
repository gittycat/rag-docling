import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const RAG_SERVER_URL = process.env.RAG_SERVER_URL || 'http://rag-server:8001';

export const DELETE: RequestHandler = async ({ params }) => {
	try {
		const { id } = params;

		if (!id) {
			return error(400, 'Document ID is required');
		}

		const response = await fetch(`${RAG_SERVER_URL}/documents/${id}`, {
			method: 'DELETE'
		});

		if (!response.ok) {
			const errorText = await response.text();
			return error(response.status, `RAG server error: ${errorText}`);
		}

		return json({ success: true });
	} catch (err) {
		console.error('Document DELETE endpoint error:', err);
		return error(500, 'Internal server error');
	}
};
