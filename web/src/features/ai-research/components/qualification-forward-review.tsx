import { useEffect, useState } from 'react';

import { usePreferences } from '../../../shared/preferences/context';
import {
  ResearchPaperPerformance,
  useResearchObservations,
  useResearchPaperBook,
} from '../ai-research-feature-boundary';
import type { ForwardReviewBinding } from '../api';

export function QualificationForwardReview({
  sourceResultId,
  binding,
  onSelect,
  disabled,
}: {
  sourceResultId: number;
  binding: ForwardReviewBinding | null;
  onSelect: (value: ForwardReviewBinding | null) => void;
  disabled: boolean;
}) {
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const [open, setOpen] = useState(false);
  const [observationId, setObservationId] = useState('');
  const observations = useResearchObservations(open, sourceResultId);
  const validObservation = observations.data?.find(
    (item) =>
      item.id === observationId &&
      item.source_backtest_result_id === sourceResultId,
  );
  const query = useResearchPaperBook(
    observationId,
    open && Boolean(validObservation),
  );
  const book = query.data;
  const performance = book?.performance;
  useEffect(() => {
    onSelect(null);
  }, [sourceResultId, observationId, book?.version, onSelect]);
  const available = Boolean(
    validObservation &&
    book?.observation_id === observationId &&
    performance?.status === 'measured' &&
    performance.through_session &&
    performance.input_version === book.version &&
    performance.sessions_since_first_accepted_target > 0 &&
    !query.isFetching &&
    !query.isError,
  );
  return (
    <details
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      className="my-4 space-y-3 text-xs"
    >
      <summary className="cursor-pointer font-semibold">
        {zh
          ? '附上已复核的前向模拟区间（可选）'
          : 'Attach a reviewed forward paper interval (optional)'}
      </summary>
      <p className="app-muted leading-5">
        {zh
          ? '选择该来源的模拟账本，复核净收益后绑定精确版本和区间。它是人工复核的补充，不替代独立检验、历史 PIT 或账户资格。'
          : 'Select a paper book for this exact source and review its net results before binding its version and interval. This supplements human review; it does not replace independent evaluation, historical PIT or account qualification.'}
      </p>
      <label className="grid gap-2">
        {zh ? '来源对应的前向观察' : 'Forward observation for this source'}
        <select
          className="app-field min-h-11 px-3"
          disabled={disabled || observations.isFetching || observations.isError}
          value={observationId}
          onChange={(event) => setObservationId(event.target.value)}
        >
          <option value="">
            {zh ? '不附上模拟区间' : 'Do not attach an interval'}
          </option>
          {observations.data
            ?.filter(
              (item) => item.source_backtest_result_id === sourceResultId,
            )
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.started_at} · {item.id.slice(0, 8)}
              </option>
            ))}
        </select>
      </label>
      {observations.isError || query.isError ? (
        <p role="alert">
          {zh
            ? '无法读取最新模拟证据，请重新读取后复核。'
            : 'Could not read current paper evidence. Reload before reviewing.'}
        </p>
      ) : null}
      {validObservation && !query.isFetching && !available ? (
        <p>
          {zh
            ? '没有可绑定的已结算真实目标区间。'
            : 'No settled interval with a real accepted target is available to bind.'}
        </p>
      ) : null}
      {available && book && performance ? (
        <>
          <ResearchPaperPerformance book={book} />
          <label className="flex items-start gap-2 leading-5">
            <input
              type="checkbox"
              disabled={disabled}
              checked={
                binding?.book_id === book.id &&
                binding.input_version === book.version
              }
              onChange={(event) =>
                onSelect(
                  event.target.checked
                    ? {
                        observation_id: observationId,
                        book_id: book.id,
                        input_version: book.version,
                        outcome_fingerprint: performance.outcome_fingerprint,
                        evaluation_start: performance.evaluation_start,
                        through_session: performance.through_session!,
                      }
                    : null,
                )
              }
            />
            <span>
              {zh
                ? '我已复核所显示的区间及模型限制，将此精确快照附入人工批准。'
                : 'I reviewed the displayed interval and model limits and will attach this exact snapshot to human approval.'}
            </span>
          </label>
        </>
      ) : null}
    </details>
  );
}
