import { useRef, useState } from 'react';

import { usePreferences } from '../../../shared/preferences/context';
import { paperBookCopy, paperBookError } from '../copy-paper-book';
import { usePublishedDatasets } from '../dataset-api';
import type { ResearchObservation } from '../observation-contracts';
import { usePaperBookCommand, useResearchPaperBook } from '../paper-book-api';
import type { PaperBookCommand } from '../paper-book-contracts';
import { ResearchPaperBookStart } from './research-paper-book-start';
import { ResearchPaperBookState } from './research-paper-book-state';

const fieldClass = 'app-field min-h-11 w-full min-w-0 px-3 py-2';
const buttonClass =
  'app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2 text-xs disabled:opacity-50';

export function ResearchPaperBookPanel({
  observation,
  busy = false,
}: {
  observation: ResearchObservation;
  busy?: boolean;
}) {
  const { locale } = usePreferences();
  const labels = paperBookCopy[locale];
  const [open, setOpen] = useState(false);
  const [datasetId, setDatasetId] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const pendingRequest = useRef<{ key: string; id: string } | null>(null);
  const query = useResearchPaperBook(observation.id, open);
  const mutation = usePaperBookCommand();
  const book = query.data;
  const datasets = usePublishedDatasets(open && Boolean(book));
  const matching =
    datasets.data?.datasets.filter(
      (item) =>
        item.cross_source_verified === true &&
        (book?.policy.corporate_action_mode === 'price_only' ||
          Boolean(item.corporate_action_evidence)) &&
        /^sha256:[0-9a-f]{64}$/.test(item.dataset_id) &&
        item.start_date === observation.source.start_date &&
        item.instruments.length === observation.universe.length &&
        new Set(
          item.instruments.map(
            (asset) => `${asset.instrument_type}:${asset.symbol}`,
          ),
        ).size === observation.universe.length &&
        item.instruments.every((asset) =>
          observation.universe.some(
            (target) =>
              target.symbol === asset.symbol &&
              target.instrument_type === asset.instrument_type,
          ),
        ),
    ) ?? [];
  const selected = matching.find((item) => item.dataset_id === datasetId);
  const waiting = busy || mutation.isPending || query.isFetching;
  const blocked = waiting || query.isError || Boolean(error);
  const failure = error ? paperBookError(error, locale) : null;

  function requestId(key: string) {
    if (pendingRequest.current?.key !== key)
      pendingRequest.current = { key, id: crypto.randomUUID() };
    return pendingRequest.current.id;
  }
  async function submit(command: PaperBookCommand) {
    setSaved(false);
    setError(null);
    try {
      await mutation.mutateAsync(command);
      pendingRequest.current = null;
      setSaved(true);
    } catch (failure) {
      setError(failure);
    }
  }
  async function refresh() {
    setSaved(false);
    const result = await query.refetch();
    if (!result.isError) setError(null);
  }

  return (
    <details
      className="min-w-0 border-t border-[var(--app-divider)] py-4"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      data-testid="research-paper-book-panel"
    >
      <summary className="cursor-pointer text-sm font-semibold">
        {labels.title}
      </summary>
      <div className="mt-3 min-w-0 space-y-4">
        <p className="app-muted text-xs leading-5">{labels.detail}</p>
        <p className="text-xs leading-5 text-[var(--app-text-secondary)]">
          {labels.boundary}
        </p>
        <button
          type="button"
          className={buttonClass}
          disabled={waiting}
          onClick={() => void refresh()}
        >
          {labels.refresh}
        </button>
        {query.isLoading ? (
          <p role="status" className="app-muted text-xs">
            {labels.loading}
          </p>
        ) : null}
        {query.isError ? (
          <p role="alert" className="text-xs leading-5">
            {labels.loadFailed}
          </p>
        ) : null}
        {failure ? (
          <div role="alert" className="space-y-2 text-xs leading-5">
            <p>{failure.message}</p>
            <p>{labels.unchanged}</p>
            <p className="break-all font-mono">{failure.code}</p>
          </div>
        ) : saved ? (
          <p role="status" className="app-muted text-xs">
            {labels.saved}
          </p>
        ) : null}
        {query.data === null && !query.isError ? (
          <ResearchPaperBookStart
            observation={observation}
            blocked={blocked}
            saving={mutation.isPending}
            onCreate={(payload) =>
              void submit({
                kind: 'create',
                observationId: observation.id,
                payload: {
                  ...payload,
                  request_id: requestId(`create:${JSON.stringify(payload)}`),
                },
              })
            }
          />
        ) : null}
        {book ? (
          <>
            <p
              className="text-sm font-semibold"
              data-testid="paper-book-lifecycle"
            >
              {book.lifecycle === 'active' ? labels.active : labels.paused}
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <label className="grid min-w-0 flex-1 basis-64 gap-2 text-xs">
                {labels.dataset}
                <select
                  className={fieldClass}
                  value={selected?.dataset_id ?? ''}
                  disabled={blocked || datasets.isFetching}
                  onChange={(event) => setDatasetId(event.target.value)}
                >
                  <option value="">{labels.choose}</option>
                  {matching.map((item) => (
                    <option key={item.dataset_id} value={item.dataset_id}>
                      {item.start_date} → {item.end_date} ·{' '}
                      {item.dataset_id.slice(7, 17)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className={buttonClass}
                disabled={waiting || datasets.isFetching}
                onClick={() => void datasets.refetch()}
              >
                {labels.refreshDatasets}
              </button>
            </div>
            <p className="app-muted text-xs leading-5">{labels.datasetHint}</p>
            {datasets.isError ? (
              <p role="alert" className="text-xs">
                {labels.datasetFailed}
              </p>
            ) : !datasets.isLoading && !matching.length ? (
              <p className="app-muted text-xs">{labels.noDatasets}</p>
            ) : null}
            {selected ? (
              <p className="break-all font-mono text-xs">
                {selected.dataset_id}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={buttonClass}
                disabled={
                  blocked ||
                  !selected ||
                  datasets.isFetching ||
                  datasets.isError
                }
                onClick={() =>
                  void submit({
                    kind: 'settle',
                    observationId: observation.id,
                    payload: {
                      request_id: requestId(
                        `settle:${book.version}:${selected!.dataset_id}`,
                      ),
                      expected_version: book.version,
                      dataset_id: selected!.dataset_id,
                    },
                  })
                }
              >
                {mutation.isPending ? labels.saving : labels.settle}
              </button>
              <button
                type="button"
                className={buttonClass}
                disabled={blocked || book.lifecycle === 'paused'}
                onClick={() =>
                  void submit({
                    kind: 'pause',
                    observationId: observation.id,
                    payload: {
                      request_id: requestId(`pause:${book.version}`),
                      expected_version: book.version,
                    },
                  })
                }
              >
                {labels.pause}
              </button>
            </div>
            <p className="app-muted text-xs leading-5">{labels.pauseHint}</p>
            <ResearchPaperBookState book={book} />
          </>
        ) : null}
      </div>
    </details>
  );
}
