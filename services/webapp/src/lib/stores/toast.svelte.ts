export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

function createToastStore() {
  let toasts = $state<Toast[]>([]);

  return {
    get items() { return toasts; },

    add(type: ToastType, message: string, duration = 5000) {
      const id = crypto.randomUUID();
      toasts = [...toasts, { id, type, message, duration }];
      if (duration > 0) setTimeout(() => this.remove(id), duration);
      return id;
    },

    remove(id: string) {
      toasts = toasts.filter(t => t.id !== id);
    },

    success(msg: string) { return this.add('success', msg); },
    error(msg: string) { return this.add('error', msg, 8000); },
    warning(msg: string) { return this.add('warning', msg); },
    info(msg: string) { return this.add('info', msg); }
  };
}

export const toast = createToastStore();
