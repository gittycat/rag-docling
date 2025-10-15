import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async () => {
	const maxUploadSizeMb = parseInt(process.env.MAX_UPLOAD_SIZE || '80', 10);

	return json({
		max_upload_size_mb: maxUploadSizeMb
	});
};
