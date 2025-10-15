export interface Message {
	role: 'user' | 'assistant';
	content: string;
}

export interface QueryRequest {
	query: string;
	session_id: string;
}

export interface QueryResponse {
	answer: string;
	session_id: string;
	sources?: string[];
}

export interface Document {
	document_id: string;
	file_name: string;
	file_type: string;
	file_size: number;
	node_count: number;
}

export interface TaskInfo {
	task_id: string;
	status: 'pending' | 'processing' | 'completed' | 'failed';
	file_name: string;
	total_chunks?: number;
	completed_chunks?: number;
	error?: string;
}

export interface BatchStatus {
	batch_id: string;
	total: number;
	completed: number;
	total_chunks: number;
	completed_chunks: number;
	tasks: Record<string, TaskInfo>;
}

export interface ModelInfo {
	llm_model: string;
	embedding_model: string;
	reranker_model?: string;
}

export interface Config {
	max_upload_size_mb: number;
}

export async function sendQuery(query: string, sessionId: string): Promise<QueryResponse> {
	const response = await fetch('/api/query', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ query, session_id: sessionId })
	});

	if (!response.ok) {
		throw new Error(`Query failed: ${response.statusText}`);
	}

	return response.json();
}

export async function getChatHistory(sessionId: string): Promise<Message[]> {
	const response = await fetch(`/api/chat/history/${sessionId}`);

	if (!response.ok) {
		throw new Error(`Failed to fetch chat history: ${response.statusText}`);
	}

	return response.json();
}

export async function clearChatHistory(sessionId: string): Promise<void> {
	const response = await fetch('/api/chat/clear', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ session_id: sessionId })
	});

	if (!response.ok) {
		throw new Error(`Failed to clear chat history: ${response.statusText}`);
	}
}

export async function getDocuments(): Promise<Document[]> {
	const response = await fetch('/api/documents');

	if (!response.ok) {
		throw new Error(`Failed to fetch documents: ${response.statusText}`);
	}

	return response.json();
}

export async function deleteDocument(documentId: string): Promise<void> {
	const response = await fetch(`/api/documents/${documentId}`, {
		method: 'DELETE'
	});

	if (!response.ok) {
		throw new Error(`Failed to delete document: ${response.statusText}`);
	}
}

export async function uploadFiles(files: File[]): Promise<string> {
	const formData = new FormData();
	files.forEach((file) => formData.append('files', file));

	const response = await fetch('/api/upload', {
		method: 'POST',
		body: formData
	});

	if (!response.ok) {
		throw new Error(`Upload failed: ${response.statusText}`);
	}

	const data = await response.json();
	return data.batch_id;
}

export async function getBatchStatus(batchId: string): Promise<BatchStatus> {
	const response = await fetch(`/api/tasks/${batchId}/status`);

	if (!response.ok) {
		throw new Error(`Failed to fetch batch status: ${response.statusText}`);
	}

	return response.json();
}

export async function getModelsInfo(): Promise<ModelInfo> {
	const response = await fetch('/api/models/info');

	if (!response.ok) {
		throw new Error(`Failed to fetch models info: ${response.statusText}`);
	}

	return response.json();
}

export async function getConfig(): Promise<Config> {
	const response = await fetch('/api/config');

	if (!response.ok) {
		throw new Error(`Failed to fetch config: ${response.statusText}`);
	}

	return response.json();
}
