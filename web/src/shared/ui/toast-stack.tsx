import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { createPortal } from 'react-dom';

import { usePreferences } from '../preferences/context';

export type ToastItem = {
  id: number;
  title: string;
  message: string;
  tone: 'success' | 'warning' | 'error';
};

export function ToastStack({ toasts }: { toasts: ToastItem[] }) {
  const { locale } = usePreferences();
  if (toasts.length === 0) {
    return null;
  }

  return createPortal(
    <div
      aria-live="polite"
      role="region"
      aria-label={locale === 'zh' ? '操作通知' : 'Notifications'}
      className="pointer-events-none fixed right-4 top-4 z-[200] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2.5"
    >
      {toasts.map((toast) => {
        const isSuccess = toast.tone === 'success';
        const Icon = isSuccess ? CheckCircle2 : AlertTriangle;
        const borderClass = isSuccess
          ? 'border-[var(--app-success-border)]'
          : toast.tone === 'warning'
            ? 'border-[var(--app-warning-border)]'
            : 'border-[var(--app-danger-border)]';
        const iconClass = isSuccess
          ? 'text-[var(--app-success-indicator)]'
          : toast.tone === 'warning'
            ? 'text-[var(--app-warning-indicator)]'
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
              <div className="mt-0.5 break-words text-xs text-[var(--app-text-secondary)] [overflow-wrap:anywhere]">
                {toast.message}
              </div>
            </div>
          </div>
        );
      })}
    </div>,
    document.body,
  );
}
