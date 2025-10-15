import { writable } from 'svelte/store';
import type { Message } from '$lib/utils/api';

export interface ChatState {
	messages: Message[];
	isLoading: boolean;
	error: string | null;
}

const initialState: ChatState = {
	messages: [],
	isLoading: false,
	error: null
};

function createChatStore() {
	const { subscribe, set, update } = writable<ChatState>(initialState);

	return {
		subscribe,
		addMessage: (message: Message) => {
			update((state) => ({
				...state,
				messages: [...state.messages, message],
				error: null
			}));
		},
		setLoading: (isLoading: boolean) => {
			update((state) => ({ ...state, isLoading }));
		},
		setError: (error: string | null) => {
			update((state) => ({ ...state, error, isLoading: false }));
		},
		setMessages: (messages: Message[]) => {
			update((state) => ({ ...state, messages }));
		},
		clearMessages: () => {
			set(initialState);
		},
		reset: () => set(initialState)
	};
}

export const chatStore = createChatStore();
