// Theme configuration for the app
// These must match the themes configured in app.css

export const themes = ['nord', 'dim'] as const;
export type Theme = (typeof themes)[number];

export const defaultTheme: Theme = 'nord';
export const darkTheme: Theme = 'dim';

export function isValidTheme(theme: string): theme is Theme {
	return themes.includes(theme as Theme);
}
