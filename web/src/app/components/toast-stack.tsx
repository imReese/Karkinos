export type ToastItem = {
  id: number;
  title: string;
  message: string;
  tone: "success" | "error";
};

const toneClassName: Record<ToastItem["tone"], string> = {
  success: "border-emerald-800/80 bg-emerald-950/70 text-emerald-100",
  error: "border-red-900/80 bg-red-950/70 text-red-100",
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
          className={`rounded-2xl border px-4 py-3 shadow-2xl shadow-black/30 ${toneClassName[toast.tone]}`}
        >
          <div className="text-sm font-semibold">{toast.title}</div>
          <div className="mt-1 text-sm opacity-90">{toast.message}</div>
        </div>
      ))}
    </div>
  );
}
