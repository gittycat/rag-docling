/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	darkMode: 'class',
	theme: {
		extend: {
			colors: {
				surface: {
					base: 'rgb(var(--surface-base) / <alpha-value>)',
					raised: 'rgb(var(--surface-raised) / <alpha-value>)',
					overlay: 'rgb(var(--surface-overlay) / <alpha-value>)',
					sunken: 'rgb(var(--surface-sunken) / <alpha-value>)'
				},
				'on-surface': {
					DEFAULT: 'rgb(var(--on-surface) / <alpha-value>)',
					muted: 'rgb(var(--on-surface-muted) / <alpha-value>)',
					subtle: 'rgb(var(--on-surface-subtle) / <alpha-value>)'
				},
				primary: {
					DEFAULT: 'rgb(var(--primary) / <alpha-value>)',
					hover: 'rgb(var(--primary-hover) / <alpha-value>)'
				},
				sidebar: {
					bg: 'rgb(var(--sidebar-bg) / <alpha-value>)',
					text: 'rgb(var(--sidebar-text) / <alpha-value>)',
					hover: 'rgb(var(--sidebar-hover) / <alpha-value>)',
					active: 'rgb(var(--sidebar-active) / <alpha-value>)'
				}
			},
			width: {
				'sidebar-expanded': 'var(--sidebar-width-expanded)',
				'sidebar-collapsed': 'var(--sidebar-width-collapsed)'
			}
		}
	}
};
