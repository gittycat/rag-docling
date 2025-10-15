import { writable } from 'svelte/store';
import type { Document, BatchStatus } from '$lib/utils/api';

export interface DocumentsState {
	documents: Document[];
	uploadingBatches: Map<string, BatchStatus>;
	isLoading: boolean;
	error: string | null;
}

const initialState: DocumentsState = {
	documents: [],
	uploadingBatches: new Map(),
	isLoading: false,
	error: null
};

function createDocumentsStore() {
	const { subscribe, set, update } = writable<DocumentsState>(initialState);

	return {
		subscribe,
		setDocuments: (documents: Document[]) => {
			update((state) => ({ ...state, documents, error: null }));
		},
		setLoading: (isLoading: boolean) => {
			update((state) => ({ ...state, isLoading }));
		},
		setError: (error: string | null) => {
			update((state) => ({ ...state, error, isLoading: false }));
		},
		addUploadingBatch: (batchId: string, batchStatus: BatchStatus) => {
			update((state) => {
				const newBatches = new Map(state.uploadingBatches);
				newBatches.set(batchId, batchStatus);
				return { ...state, uploadingBatches: newBatches };
			});
		},
		updateBatchStatus: (batchId: string, batchStatus: BatchStatus) => {
			update((state) => {
				const newBatches = new Map(state.uploadingBatches);
				newBatches.set(batchId, batchStatus);
				return { ...state, uploadingBatches: newBatches };
			});
		},
		removeBatch: (batchId: string) => {
			update((state) => {
				const newBatches = new Map(state.uploadingBatches);
				newBatches.delete(batchId);
				return { ...state, uploadingBatches: newBatches };
			});
		},
		removeDocument: (documentId: string) => {
			update((state) => ({
				...state,
				documents: state.documents.filter((doc) => doc.document_id !== documentId)
			}));
		},
		reset: () => set(initialState)
	};
}

export const documentsStore = createDocumentsStore();
