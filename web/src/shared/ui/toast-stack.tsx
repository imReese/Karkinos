export type ToastItem = {
  id: number;
  title: string;
  message: string;
  tone: 'success' | 'error';
};

const toneClassName: Record<ToastItem['tone'], string> = {
  success:
    'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]',
  error:
    'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger-text)]',
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
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className={`rounded-[var(--app-radius-surface)] border px-4 py-3 shadow-[var(--app-shadow-overlay)] backdrop-blur-sm ${toneClassName[toast.tone]}`}
        >
          <div className="text-sm font-semibold">{toast.title}</div>
          <div className="mt-0.5 text-xs opacity-90">{toast.message}</div>
        </div>
      ))}
    </div>
  );
}
