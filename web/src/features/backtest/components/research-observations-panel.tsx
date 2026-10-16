import { useRef, useState } from 'react';

import { formatTimestamp } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import type { BacktestReport } from '../api';
import { observationCopy, observationError } from '../copy-observations';
import {
  useConfigureObservationAutomation,
  useObservationCommand,
  useResearchObservations,
} from '../observation-api';
import type {
  ObservationCommand,
  ResearchObservation,
} from '../observation-contracts';
import { usePaperBookCommand } from '../paper-book-api';
import { ResearchObservationDetail } from './research-observation-detail';
import { ObservationForwardInput } from './observation-forward-input';
import {
  configuredHealthPolicy,
  ObservationHealthSettings,
  type ObservationHealthDraft,
} from './observation-health-settings';

const fieldClass = 'app-field min-h-11 w-full min-w-0 px-3 py-2';
const buttonClass =
  'app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2 text-xs disabled:opacity-50';

export function ResearchObservationsPanel({
  report,
  continuousStart = false,
}: {
  report: BacktestReport;
  continuousStart?: boolean;
}) {
  return (
    <ObservationPanel
      key={report.id}
      report={report}
      continuousStart={continuousStart}
    />
  );
}

type ForwardSetup = { initialCash: string; authorized: boolean };

function ObservationPanel({
  report,
  continuousStart,
}: {
  report: BacktestReport;
  continuousStart: boolean;
}) {
  const { locale } = usePreferences();
  const labels = observationCopy[locale];
  const [open, setOpen] = useState(true);
  const [selectedId, setSelectedId] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const pendingRequest = useRef<{ key: string; id: string } | null>(null);
  const query = useResearchObservations(open, report.id);
  const mutation = useObservationCommand();
  const paperMutation = usePaperBookCommand();
  const automationMutation = useConfigureObservationAutomation();
  const [starting, setStarting] = useState(false);
  const [incompleteStart, setIncompleteStart] = useState(false);
  const sequence = useRef<{
    command: Extract<ObservationCommand, { kind: 'start' }>;
    setup: ForwardSetup;
    bookRequestId: string;
    costs: BacktestReport['config']['cost_assumptions'];
    observation?: ResearchObservation;
    automationAttempted?: boolean;
  } | null>(null);
  const observations =
    query.data?.filter(
      (item) => item.source_backtest_result_id === report.id,
    ) ?? [];
  const observation =
    observations.find((item) => item.id === selectedId) ?? observations[0];

  function requestId(key: string) {
    if (pendingRequest.current?.key !== key)
      pendingRequest.current = { key, id: crypto.randomUUID() };
    return pendingRequest.current.id;
  }

  async function submit(command: ObservationCommand) {
    setError(null);
    setSaved(false);
    try {
      const result = await mutation.mutateAsync(command);
      setSelectedId(result.id);
      pendingRequest.current = null;
      setSaved(true);
    } catch (failure) {
      setError(failure);
    }
  }

  async function finishContinuousStart() {
    const frozen = sequence.current;
    if (!frozen) return;
    setStarting(true);
    setError(null);
    setSaved(false);
    try {
      const current =
        frozen.observation ?? (await mutation.mutateAsync(frozen.command));
      frozen.observation = current;
      setSelectedId(current.id);
      // Create the financial book before any automatic target can be accepted.
      await paperMutation.mutateAsync({
        kind: 'create',
        observationId: current.id,
        payload: {
          request_id: frozen.bookRequestId,
          initial_cash: frozen.setup.initialCash,
          ...(frozen.costs ? { cost_assumptions: frozen.costs } : {}),
        },
      });
      let alreadyEnabled = false;
      if (frozen.automationAttempted) {
        const fresh = await query.refetch();
        if (fresh.isError) throw fresh.error;
        const latest = fresh.data?.find((item) => item.id === current.id);
        alreadyEnabled = Boolean(
          latest?.automation?.enabled &&
          latest.automation.paper_settlement_enabled &&
          latest.automation.dataset_preparation_enabled,
        );
        if (
          !alreadyEnabled &&
          latest?.automation?.generation !== current.automation?.generation
        )
          throw new Error(
            locale === 'zh'
              ? '自动运行设置已变化，请先核对下方已有观察的设置。'
              : 'Automation settings changed. Review the saved observation controls below.',
          );
      }
      if (!alreadyEnabled) {
        frozen.automationAttempted = true;
        await automationMutation.mutateAsync({
          observationId: current.id,
          sourceResultId: report.id,
          enabled: true,
          paperSettlementEnabled: true,
          datasetPreparationEnabled: true,
          expectedGeneration: current.automation?.generation ?? null,
        });
      }
      sequence.current = null;
      pendingRequest.current = null;
      setIncompleteStart(false);
      setSaved(true);
    } catch (failure) {
      setError(failure);
      setIncompleteStart(true);
    } finally {
      setStarting(false);
    }
  }

  return (
    <details
      className="min-w-0 border-y border-[var(--app-divider)] py-4"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      data-testid="research-observations-panel"
    >
      <summary className="cursor-pointer text-sm font-semibold">
        {labels.title}
      </summary>
      <div className="mt-3 min-w-0 space-y-4">
        <p className="text-xs leading-5 text-[var(--app-text-secondary)]">
          {continuousStart
            ? locale === 'zh'
              ? '使用独立虚拟资金、模拟成交和成本；已保存来源决定实验范围。不会改变账户建议来源或交易权限。'
              : 'Uses isolated virtual cash, modeled fills and costs within the saved source scope. Account recommendation and trading permissions are separate.'
            : labels.boundary}
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="grid min-w-0 flex-1 basis-64 gap-2 text-xs">
            {labels.select}
            <select
              className={fieldClass}
              value={observation?.id ?? ''}
              disabled={mutation.isPending || !observations.length}
              onChange={(event) => {
                setSelectedId(event.target.value);
                setSaved(false);
                setError(null);
              }}
            >
              {!observations.length ? (
                <option value="">{labels.none}</option>
              ) : null}
              {observations.map((item) => (
                <option value={item.id} key={item.id}>
                  {formatTimestamp(item.started_at)} ·{' '}
                  {item.lifecycle === 'active' ? labels.active : labels.paused}{' '}
                  · {item.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <button
            className={buttonClass}
            type="button"
            disabled={mutation.isPending || query.isFetching}
            onClick={() => {
              setError(null);
              void query.refetch();
            }}
          >
            {labels.refresh}
          </button>
        </div>
        {query.isLoading ? (
          <p role="status" className="app-muted text-xs">
            {labels.loading}
          </p>
        ) : null}
        {query.isError ? (
          <p role="alert" className="text-xs">
            {labels.loadFailed}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-xs leading-5">
            {observationError(error, locale)}
          </p>
        ) : saved ? (
          <p role="status" className="app-muted text-xs">
            {labels.saved}
          </p>
        ) : null}
        {observation ? (
          <ResearchObservationDetail
            key={observation.id}
            observation={observation}
            busy={mutation.isPending}
            readBusy={query.isFetching}
            readFailed={query.isError}
            onRefresh={async () => !(await query.refetch()).isError}
            onCommand={(kind, datasetId) => {
              const payload = {
                expected_version: observation.version,
                ...(kind === 'advance' ? { dataset_id: datasetId! } : {}),
              };
              const id = requestId(
                `${kind}:${observation.id}:${JSON.stringify(payload)}`,
              );
              if (kind === 'advance')
                void submit({
                  kind,
                  id: observation.id,
                  payload: {
                    request_id: id,
                    expected_version: observation.version,
                    dataset_id: datasetId!,
                  },
                });
              else
                void submit({
                  kind,
                  id: observation.id,
                  payload: {
                    request_id: id,
                    expected_version: observation.version,
                  },
                });
            }}
          />
        ) : null}
        <details
          className="border-t border-[var(--app-divider)] py-4"
          data-testid="observation-start-disclosure"
        >
          <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">
            {locale === 'zh'
              ? '创建新的前向观察或模拟'
              : 'Start a new forward observation or paper experiment'}
          </summary>
          <div className="mt-4">
            <ObservationStartForm
              report={report}
              continuousStart={continuousStart}
              saving={mutation.isPending || starting}
              busy={
                mutation.isPending ||
                starting ||
                incompleteStart ||
                query.isLoading ||
                query.isError
              }
              onStart={(payload, setup) => {
                const command: Extract<ObservationCommand, { kind: 'start' }> =
                  {
                    kind: 'start',
                    payload: {
                      ...payload,
                      request_id: requestId(`start:${JSON.stringify(payload)}`),
                    },
                  };
                if (continuousStart && setup?.authorized) {
                  sequence.current = {
                    command,
                    setup,
                    bookRequestId: crypto.randomUUID(),
                    costs: report.config.cost_assumptions
                      ? { ...report.config.cost_assumptions }
                      : null,
                  };
                  void finishContinuousStart();
                } else void submit(command);
              }}
            />
          </div>
        </details>
        <details className="border-t border-[var(--app-divider)] py-4">
          <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">
            {locale === 'zh'
              ? '模拟方法与权限边界'
              : 'Simulation method and authority boundaries'}
          </summary>
          <p className="app-muted mt-4 text-xs leading-5">
            {continuousStart
              ? locale === 'zh'
                ? '冻结已保存候选，先创建独立模拟账本，再连续准备已核验数据、发布目标并结算。'
                : 'Freeze the saved candidate, create its independent paper book, then prepare verified data, publish targets and settle continuously.'
              : labels.detail}
          </p>
        </details>
        {incompleteStart ? (
          <div role="status" className="space-y-2 text-xs">
            <p>
              {locale === 'zh'
                ? '启动尚未完成。已创建的观察和账本保留；重试沿用原请求，不补造目标。'
                : 'Setup is incomplete. Created observations and books are preserved; resuming reuses the original requests without inventing targets.'}
            </p>
            <button
              type="button"
              className={buttonClass}
              disabled={starting}
              onClick={() => void finishContinuousStart()}
            >
              {locale === 'zh' ? '继续完成模拟启动' : 'Resume paper setup'}
            </button>
          </div>
        ) : null}
      </div>
    </details>
  );
}

function ObservationStartForm({
  report,
  busy,
  saving,
  continuousStart,
  onStart,
}: {
  report: BacktestReport;
  continuousStart: boolean;
  busy: boolean;
  saving: boolean;
  onStart: (
    payload: Omit<
      Extract<ObservationCommand, { kind: 'start' }>['payload'],
      'request_id'
    >,
    setup?: ForwardSetup,
  ) => void;
}) {
  const { locale } = usePreferences();
  const labels = observationCopy[locale];
  const [useForwardInput, setUseForwardInput] = useState(
    !report.config.dataset_id,
  );
  const [forwardInput, setForwardInput] = useState<{
    datasetId: string | null;
    busy: boolean;
  }>({ datasetId: null, busy: false });
  const [initialCash, setInitialCash] = useState('100000');
  const [authorized, setAuthorized] = useState(false);
  const paperReady =
    !continuousStart ||
    (authorized &&
      /^\d+(?:\.\d+)?$/.test(initialCash) &&
      Number(initialCash) > 0);
  const [horizon, setHorizon] = useState('5');
  const [symbolLimit, setSymbolLimit] = useState('0.25');
  const [grossLimit, setGrossLimit] = useState('1');
  const [health, setHealth] = useState<ObservationHealthDraft>({
    enabled: false,
    mode: 'observe_only',
    window: '',
    minimum: '',
    threshold: '',
  });
  const healthPolicy = configuredHealthPolicy(health);
  const supported = ['dual_ma', 'ai_formula_research', 'etf_rotation'].includes(
    report.config.strategy,
  );
  const inputReady =
    !useForwardInput || (!!forwardInput.datasetId && !forwardInput.busy);
  const valid =
    Number.isInteger(Number(horizon)) &&
    Number(horizon) >= 1 &&
    Number(horizon) <= 60 &&
    [symbolLimit, grossLimit].every(
      (value) =>
        value.trim() !== '' &&
        Number.isFinite(Number(value)) &&
        Number(value) > 0 &&
        Number(value) <= 1,
    );
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (
          valid &&
          paperReady &&
          inputReady &&
          healthPolicy !== undefined &&
          supported &&
          !busy
        )
          onStart(
            {
              source_backtest_result_id: report.id,
              ...(useForwardInput && forwardInput.datasetId
                ? { forward_dataset_id: forwardInput.datasetId }
                : {}),
              horizon_sessions: Number(horizon),
              max_symbol_weight: symbolLimit.trim(),
              max_gross_weight: grossLimit.trim(),
              health_policy: healthPolicy,
            },
            continuousStart ? { initialCash, authorized } : undefined,
          );
      }}
    >
      <fieldset disabled={busy} className="min-w-0 space-y-3">
        <legend className="text-xs font-semibold">{labels.setup}</legend>
        {supported ? (
          <>
            <label className="flex items-start gap-2 text-xs leading-5">
              <input
                type="checkbox"
                checked={useForwardInput}
                onChange={(event) => setUseForwardInput(event.target.checked)}
              />
              {locale === 'zh'
                ? '为新观察选择或准备独立预热数据'
                : 'Choose or prepare separate warmup data for this new observation'}
            </label>
            {useForwardInput ? (
              <ObservationForwardInput
                sourceResultId={report.id}
                disabled={busy}
                onChange={setForwardInput}
              />
            ) : null}
          </>
        ) : null}
        <div className="grid min-w-0 gap-3 sm:grid-cols-3">
          <label className="grid min-w-0 gap-2 text-xs">
            {labels.horizon}
            <input
              className={fieldClass}
              type="number"
              min="1"
              max="60"
              step="1"
              value={horizon}
              onChange={(event) => setHorizon(event.target.value)}
            />
          </label>
          <label className="grid min-w-0 gap-2 text-xs">
            {labels.symbolLimit}
            <input
              className={fieldClass}
              type="number"
              min="0"
              max="1"
              step="any"
              value={symbolLimit}
              onChange={(event) => setSymbolLimit(event.target.value)}
            />
          </label>
          <label className="grid min-w-0 gap-2 text-xs">
            {labels.grossLimit}
            <input
              className={fieldClass}
              type="number"
              min="0"
              max="1"
              step="any"
              value={grossLimit}
              onChange={(event) => setGrossLimit(event.target.value)}
            />
          </label>
        </div>
        {continuousStart ? (
          <div className="space-y-3 border-y border-[var(--app-divider)] py-3 text-xs">
            <label className="grid max-w-sm gap-2">
              {locale === 'zh'
                ? '模拟初始资金（人民币）'
                : 'Paper initial cash (CNY)'}
              <input
                className={fieldClass}
                inputMode="decimal"
                value={initialCash}
                onChange={(event) => setInitialCash(event.target.value)}
              />
            </label>
            <p className="app-muted">
              {locale === 'zh'
                ? '冻结本报告的成本设置（未指定时采用平台默认）。先创建独立账本，再启用核验数据准备、每日目标与模拟结算。模拟范围以已保存来源为准。'
                : 'Freeze this report’s cost inputs, or the platform defaults when absent. Create the independent book first, then enable verified data preparation, daily targets and paper settlement. The saved source defines the simulation scope.'}
            </p>
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={authorized}
                onChange={(event) => setAuthorized(event.target.checked)}
              />
              {locale === 'zh'
                ? '授权本次冻结模拟的数据准备、目标发布与结算；账户推荐发布另行授权。'
                : 'Authorize data preparation, target publication and settlement for this frozen simulation; account recommendation publication is authorized separately.'}
            </label>
          </div>
        ) : null}
        <ObservationHealthSettings value={health} onChange={setHealth} />
        {!valid ? (
          <p className="text-xs" role="alert">
            {labels.invalid}
          </p>
        ) : null}
        {!supported ? (
          <p className="app-muted text-xs leading-5">{labels.unsupported}</p>
        ) : null}
        <button
          className={buttonClass}
          type="submit"
          disabled={
            !valid ||
            !paperReady ||
            !inputReady ||
            healthPolicy === undefined ||
            !supported
          }
        >
          {saving
            ? labels.busy
            : continuousStart
              ? locale === 'zh'
                ? '冻结并启动前向模拟'
                : 'Freeze and start forward paper'
              : labels.start}
        </button>
      </fieldset>
    </form>
  );
}
