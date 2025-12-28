import { writable } from 'svelte/store';

// Store for export function - set by chat page, called by sidebar
export const exportChatFn = writable<(() => void) | null>(null);

// Store to track if export is available (has messages)
export const canExportChat = writable(false);
