import { Button, EvidenceState } from '../../../shared/ui/workbench';

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
    <EvidenceState
      kind={tone === 'danger' ? 'error' : 'empty'}
      title={title}
      description={detail}
      action={
        actionLabel && onAction ? (
          <Button variant="secondary" onClick={onAction}>
            {actionLabel}
          </Button>
        ) : undefined
      }
    />
  );
}
