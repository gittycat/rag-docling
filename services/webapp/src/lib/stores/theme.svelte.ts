import { browser } from '$app/environment';

export type Theme = 'dark' | 'light' | 'system';

function getSystemTheme(): 'dark' | 'light' {
  if (!browser) return 'dark';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function createThemeStore() {
  const stored = browser ? localStorage.getItem('theme') as Theme : null;
  let preference = $state<Theme>(stored || 'system');
  let systemTheme = $state<'dark' | 'light'>(getSystemTheme());

  const resolved = $derived<'dark' | 'light'>(
    preference === 'system' ? systemTheme : preference
  );

  if (browser) {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', (e) => {
      systemTheme = e.matches ? 'dark' : 'light';
    });

    $effect(() => {
      applyTheme(resolved);
    });
  }

  function applyTheme(theme: 'dark' | 'light') {
    if (!browser) return;
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }

  return {
    get preference() { return preference; },
    get resolved() { return resolved; },
    get isDark() { return resolved === 'dark'; },

    setPreference(value: Theme) {
      preference = value;
      if (value !== 'system') {
        systemTheme = value;
      } else {
        systemTheme = getSystemTheme();
      }
      if (browser) {
        localStorage.setItem('theme', value);
      }
    },

    toggle() {
      this.setPreference(resolved === 'dark' ? 'light' : 'dark');
    }
  };
}

export const theme = createThemeStore();
