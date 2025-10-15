const SESSION_KEY = 'rag_session_id';

export function getSessionId(): string {
	if (typeof window === 'undefined') {
		return '';
	}

	let sessionId = localStorage.getItem(SESSION_KEY);
	if (!sessionId) {
		sessionId = crypto.randomUUID();
		localStorage.setItem(SESSION_KEY, sessionId);
	}
	return sessionId;
}

export function clearSession(): void {
	if (typeof window !== 'undefined') {
		localStorage.removeItem(SESSION_KEY);
	}
}
