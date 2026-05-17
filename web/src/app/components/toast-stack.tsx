export type ToastItem = {
  id: number;
  title: string;
  message: string;
  tone: 'success' | 'error';
};

const toneClassName: Record<ToastItem['tone'], string> = {
  success:
    'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success)]',
  error:
    'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger)]',
};

export function ToastStack({ toasts }: { toasts: ToastItem[] }) {
  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed right-4 top-4 z-50 flex w-full max-w-sm flex-col gap-3">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`rounded-2xl border px-4 py-3 ${toneClassName[toast.tone]}`}
        >
          <div className="text-sm font-semibold">{toast.title}</div>
          <div className="mt-1 text-sm opacity-90">{toast.message}</div>
        </div>
      ))}
    </div>
  );
}
