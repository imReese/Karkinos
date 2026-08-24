export function OverviewStatusCard({
  title,
  detail,
  tone = 'default',
  actionLabel,
  onAction,
}: {
  title: string;
  detail: string;
  tone?: 'default' | 'danger';
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div
      className={
        tone === 'danger'
          ? 'app-panel-danger rounded-3xl p-4 sm:p-5'
          : 'app-terminal-panel rounded-3xl p-4 sm:p-5'
      }
    >
      <div className="app-type-subsection-title">{title}</div>
      <div className="mt-2 text-sm opacity-80">{detail}</div>
      {actionLabel && onAction ? (
        <button
          type="button"
          onClick={onAction}
          className="app-button-secondary mt-4 rounded-2xl px-4 py-2 text-sm"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}
