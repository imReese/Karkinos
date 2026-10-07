import { AlertTriangle, CheckCircle2 } from 'lucide-react';

export type ToastItem = {
  id: number;
  title: string;
  message: string;
  tone: 'success' | 'error';
};

export function ToastStack({ toasts }: { toasts: ToastItem[] }) {
  if (toasts.length === 0) {
    return null;
  }

  return (
    <div
      aria-live="polite"
      role="region"
      aria-label="Notifications"
      className="pointer-events-none fixed right-4 top-4 z-50 flex w-full max-w-sm flex-col gap-2.5"
    >
      {toasts.map((toast) => {
        const isSuccess = toast.tone === 'success';
        const Icon = isSuccess ? CheckCircle2 : AlertTriangle;
        const borderClass = isSuccess
          ? 'border-[var(--app-success-border)]'
          : 'border-[var(--app-danger-border)]';
        const iconClass = isSuccess
          ? 'text-[var(--app-success-indicator)]'
          : 'text-[var(--app-danger-indicator)]';

        return (
          <div
            key={toast.id}
            role="status"
            className={`pointer-events-auto flex items-start gap-3 rounded-[var(--app-radius-surface)] border ${borderClass} bg-[var(--app-surface-overlay)] px-4 py-3 shadow-[var(--app-shadow-overlay)] backdrop-blur-sm`}
          >
            <Icon
              className={`mt-0.5 h-4 w-4 shrink-0 ${iconClass}`}
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {toast.title}
              </div>
              <div className="mt-0.5 text-xs text-[var(--app-text-secondary)]">
                {toast.message}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
