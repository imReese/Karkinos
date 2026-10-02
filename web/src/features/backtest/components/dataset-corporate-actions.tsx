import { useEffect, useState } from 'react';

import type { Locale } from '../../../shared/locale';
import { corporateActionCopy } from '../copy-corporate-actions';
import {
  datasetErrorMessage,
  useCollectDatasetCorporateActions,
  type PublishedDataset,
} from '../dataset-api';
import { CorporateActionEvidencePanel } from './corporate-action-evidence-panel';

export function DatasetCorporateActions({
  dataset,
  locale,
  busy,
  onSelect,
  onPendingChange,
}: {
  dataset: PublishedDataset | null;
  locale: Locale;
  busy: boolean;
  onSelect: (dataset: PublishedDataset) => void;
  onPendingChange: (pending: boolean) => void;
}) {
  const collect = useCollectDatasetCorporateActions();
  const [error, setError] = useState('');
  const [completed, setCompleted] = useState<{
    datasetId: string;
    message: string;
  } | null>(null);
  const labels = corporateActionCopy[locale];
  useEffect(() => {
    onPendingChange(collect.isPending);
    return () => onPendingChange(false);
  }, [collect.isPending, onPendingChange]);
  useEffect(() => setError(''), [dataset?.dataset_id]);

  if (!dataset) return null;
  const selected = dataset;
  const supported =
    selected.instruments.length > 0 &&
    selected.instruments.every(
      (instrument) => instrument.instrument_type === 'stock',
    );
  const refresh = Boolean(selected.corporate_action_evidence);

  async function collectEvidence() {
    setError('');
    setCompleted(null);
    try {
      const next = await collect.mutateAsync({
        datasetId: selected.dataset_id,
        refresh,
      });
      onSelect(next);
      setCompleted({
        datasetId: next.dataset_id,
        message:
          next.dataset_id === selected.dataset_id
            ? labels.reused
            : labels.success,
      });
    } catch (failure) {
      setError(datasetErrorMessage(failure, locale === 'zh'));
    }
  }

  return (
    <div className="grid min-w-0 gap-3" aria-busy={collect.isPending}>
      <CorporateActionEvidencePanel
        evidence={selected.corporate_action_evidence}
        locale={locale}
      />
      <p className="app-muted text-xs leading-5">{labels.actionScope}</p>
      {!supported ? (
        <p className="app-muted text-xs leading-5">{labels.unsupported}</p>
      ) : null}
      <button
        type="button"
        className="app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2"
        disabled={busy || collect.isPending || !supported}
        onClick={() => void collectEvidence()}
      >
        {collect.isPending
          ? labels.pending
          : refresh
            ? labels.refresh
            : labels.collect}
      </button>
      {completed?.datasetId === selected.dataset_id ? (
        <p role="status" className="text-xs leading-5">
          {completed.message}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-[var(--app-danger)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
