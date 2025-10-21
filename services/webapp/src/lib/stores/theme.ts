import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export type Theme = 'dark' | 'light';

function createThemeStore() {
	const stored = browser ? localStorage.getItem('theme') : null;
	const initialTheme: Theme = (stored as Theme) || 'dark';

	const { subscribe, set, update } = writable<Theme>(initialTheme);

	return {
		subscribe,
		toggle: () => {
			update((current) => {
				const newTheme = current === 'dark' ? 'light' : 'dark';
				if (browser) {
					localStorage.setItem('theme', newTheme);
				}
				return newTheme;
			});
		},
		set: (theme: Theme) => {
			if (browser) {
				localStorage.setItem('theme', theme);
			}
			set(theme);
		}
	};
}

export const themeStore = createThemeStore();
