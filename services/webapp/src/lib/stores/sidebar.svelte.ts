import { browser } from '$app/environment';

function createSidebarStore() {
  const stored = browser ? localStorage.getItem('sidebar-collapsed') : null;
  let collapsed = $state(stored === 'true');

  return {
    get collapsed() { return collapsed; },
    toggle() {
      collapsed = !collapsed;
      if (browser) localStorage.setItem('sidebar-collapsed', String(collapsed));
    },
    setCollapsed(value: boolean) {
      collapsed = value;
      if (browser) localStorage.setItem('sidebar-collapsed', String(value));
    }
  };
}

export const sidebar = createSidebarStore();
