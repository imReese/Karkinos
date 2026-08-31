import { useEffect, useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { formatPublicOperationalNote } from '../../../shared/public-labels';
import { ControlledActionZone } from '../../../shared/ui/workbench';
import {
  useAutomaticTradingQuery,
  useSetAutomaticTradingMutation,
  type AutomaticTradingSnapshot,
  type AutomaticTradingStatus,
} from '../api';

const ENABLE_ACKNOWLEDGEMENT =
  'enable_bounded_automatic_trading_gate_without_capital_authority' as const;
const DISABLE_ACKNOWLEDGEMENT =
  'disable_automatic_trading_gate_immediately' as const;

const VALIDITY_OPTIONS = [
  { seconds: 3_600, label: 'oneHour' },
  { seconds: 14_400, label: 'fourHours' },
  { seconds: 28_800, label: 'eightHours' },
  { seconds: 43_200, label: 'twelveHours' },
] as const;

type PresentedAutomaticTradingState = AutomaticTradingStatus | 'loading';

export function AutomaticTradingPanel() {
  const copy = useCopy();
  const labels = copy.trading.automaticTrading;
  const { locale } = usePreferences();
  const automaticTrading = useAutomaticTradingQuery();
  const setAutomaticTrading = useSetAutomaticTradingMutation();
  const [operatorId, setOperatorId] = useState('');
  const [reason, setReason] = useState('');
  const [ttlSeconds, setTtlSeconds] = useState(28_800);
  const [formError, setFormError] = useState<string | null>(null);

  const snapshot = automaticTrading.data ?? null;
  const state = automaticTrading.isLoading
    ? 'loading'
    : automaticTrading.isError
      ? 'unavailable'
      : resolveAutomaticTradingState(snapshot);
  const canEnable = state === 'disabled';
  const canDisable = state === 'enabled' || state === 'expired';
  const controlsAvailable = canEnable || canDisable;

  useEffect(() => {
    if (snapshot?.operator_id) {
      setOperatorId(snapshot.operator_id);
    }
    if (snapshot?.reason) {
      setReason(snapshot.reason);
    }
  }, [snapshot?.operator_id, snapshot?.reason]);

  const updateGate = async (nextEnabled: boolean) => {
    if (
      snapshot === null ||
      (nextEnabled ? !canEnable : !canDisable) ||
      !Number.isInteger(snapshot.revision)
    ) {
      return;
    }

    const trimmedOperatorId = operatorId.trim();
    const trimmedReason = reason.trim();
    if (!trimmedOperatorId) {
      setFormError(labels.operatorRequired);
      return;
    }
    if (!trimmedReason) {
      setFormError(labels.reasonRequired);
      return;
    }

    setFormError(null);
    try {
      await setAutomaticTrading.mutateAsync(
        nextEnabled
          ? {
              enabled: true,
              reason: trimmedReason,
              operator_id: trimmedOperatorId,
              expected_revision: snapshot.revision,
              ttl_seconds: ttlSeconds,
              acknowledgement: ENABLE_ACKNOWLEDGEMENT,
            }
          : {
              enabled: false,
              reason: trimmedReason,
              operator_id: trimmedOperatorId,
              expected_revision: snapshot.revision,
              acknowledgement: DISABLE_ACKNOWLEDGEMENT,
            },
      );
    } catch {
      // The mutation exposes the backend error below without leaving a rejected
      // event-handler promise behind.
    }
  };

  const evidence = snapshot ? (
    <span className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
      <span>
        {labels.revision}: {snapshot.revision}
      </span>
      <span>
        {labels.updatedAt}: {formatTimestamp(snapshot.updated_at, locale)}
      </span>
      <span>
        {labels.effectiveAt}: {formatTimestamp(snapshot.effective_at, locale)}
      </span>
      <span>
        {labels.expiresAt}: {formatTimestamp(snapshot.expires_at, locale)}
      </span>
    </span>
  ) : null;

  return (
    <div
      className="min-w-0 sm:col-span-2"
      data-automatic-trading-state={state}
      data-testid="automatic-trading-panel"
    >
      <ControlledActionZone
        title={labels.title}
        description={labels.subtitle}
        evidence={evidence}
        layout="stack"
      >
        <div className="grid w-full min-w-0 gap-3">
          <AutomaticTradingStatusBadge state={state} />

          {automaticTrading.isError || state === 'unavailable' ? (
            <p
              className="app-error-text text-sm"
              data-testid="automatic-trading-load-error"
            >
              {labels.loadFailed}
            </p>
          ) : null}

          <div className="grid min-w-0 gap-2 sm:grid-cols-2">
            <label className="grid min-w-0 gap-1.5">
              <span className="text-sm font-medium">{labels.operatorId}</span>
              <input
                value={operatorId}
                onChange={(event) => {
                  setOperatorId(event.target.value);
                  setFormError(null);
                }}
                placeholder={labels.operatorPlaceholder}
                className="app-field h-10 min-w-0 rounded-xl px-3 text-sm"
                aria-label={labels.operatorId}
                disabled={!controlsAvailable || setAutomaticTrading.isPending}
              />
            </label>
            <label className="grid min-w-0 gap-1.5">
              <span className="text-sm font-medium">{labels.reason}</span>
              <input
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                  setFormError(null);
                }}
                placeholder={labels.reasonPlaceholder}
                className="app-field h-10 min-w-0 rounded-xl px-3 text-sm"
                aria-label={labels.reason}
                disabled={!controlsAvailable || setAutomaticTrading.isPending}
              />
            </label>
          </div>

          <label className="grid min-w-0 gap-1.5 sm:max-w-56">
            <span className="text-sm font-medium">{labels.validity}</span>
            <select
              value={ttlSeconds}
              onChange={(event) => setTtlSeconds(Number(event.target.value))}
              className="app-field h-10 min-w-0 rounded-xl px-3 text-sm"
              aria-label={labels.validity}
              disabled={!canEnable || setAutomaticTrading.isPending}
            >
              {VALIDITY_OPTIONS.map((option) => (
                <option key={option.seconds} value={option.seconds}>
                  {labels[option.label]}
                </option>
              ))}
            </select>
          </label>

          {formError ? (
            <p className="app-error-text text-sm" role="alert">
              {formError}
            </p>
          ) : null}
          {setAutomaticTrading.isError ? (
            <p className="app-error-text text-sm" role="alert">
              {getErrorMessage(setAutomaticTrading.error)}
            </p>
          ) : null}

          <div className="grid min-w-0 gap-2 sm:grid-cols-2">
            <button
              type="button"
              className="app-button-danger min-h-10 rounded-xl px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-45"
              disabled={!canEnable || setAutomaticTrading.isPending}
              onClick={() => void updateGate(true)}
            >
              {setAutomaticTrading.isPending && canEnable
                ? labels.submitting
                : labels.enable}
            </button>
            <button
              type="button"
              className="app-button-secondary min-h-10 rounded-xl px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-45"
              disabled={!canDisable || setAutomaticTrading.isPending}
              onClick={() => void updateGate(false)}
            >
              {setAutomaticTrading.isPending && canDisable
                ? labels.submitting
                : labels.disable}
            </button>
          </div>

          <div className="grid gap-1 border-l-2 border-[var(--app-warning-border)] pl-3 text-xs leading-5 text-[var(--app-warning-text)]">
            <p>{labels.noRestart}</p>
            <p>{labels.noCapitalAuthority}</p>
            <p>{labels.brokerSubmissionNotImplemented}</p>
          </div>

          {snapshot && Array.isArray(snapshot.blockers) ? (
            <div className="text-xs leading-5 text-[var(--app-text-secondary)]">
              <span className="font-semibold">{labels.blockers}: </span>
              {snapshot.blockers.length
                ? snapshot.blockers
                    .map((blocker) =>
                      formatPublicOperationalNote(blocker, locale),
                    )
                    .join('; ')
                : labels.noBlockers}
            </div>
          ) : null}
        </div>
      </ControlledActionZone>
    </div>
  );
}

function AutomaticTradingStatusBadge({
  state,
}: {
  state: PresentedAutomaticTradingState;
}) {
  const labels = useCopy().trading.automaticTrading;
  const label =
    state === 'loading'
      ? labels.loading
      : state === 'enabled'
        ? labels.enabled
        : state === 'disabled'
          ? labels.disabled
          : state === 'expired'
            ? labels.expired
            : labels.unavailable;
  const tone =
    state === 'expired' || state === 'disabled'
      ? 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]'
      : 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger-text)]';

  return (
    <span
      className={`inline-flex w-fit items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${tone}`}
      data-testid="automatic-trading-status"
    >
      {label}
    </span>
  );
}

function resolveAutomaticTradingState(
  snapshot: AutomaticTradingSnapshot | null,
): AutomaticTradingStatus {
  if (
    snapshot === null ||
    typeof snapshot !== 'object' ||
    Array.isArray(snapshot) ||
    typeof snapshot.enabled !== 'boolean' ||
    typeof snapshot.configured_enabled !== 'boolean' ||
    !Number.isInteger(snapshot.revision) ||
    snapshot.revision < 0 ||
    typeof snapshot.control_fingerprint !== 'string' ||
    typeof snapshot.reason !== 'string' ||
    typeof snapshot.operator_id !== 'string' ||
    !isNullableString(snapshot.effective_at) ||
    !isNullableString(snapshot.expires_at) ||
    !isNullableString(snapshot.updated_at) ||
    !Array.isArray(snapshot.blockers) ||
    !snapshot.blockers.every((blocker) => typeof blocker === 'string') ||
    snapshot.grants_capital_authority !== false ||
    snapshot.automatic_broker_submission_implemented !== false
  ) {
    return 'unavailable';
  }

  if (snapshot.status === 'enabled') {
    const expiry = parseTimestamp(snapshot.expires_at);
    if (
      snapshot.configured_enabled === true &&
      expiry !== null &&
      expiry <= Date.now()
    ) {
      return 'expired';
    }
    return snapshot.enabled === true &&
      snapshot.configured_enabled === true &&
      expiry !== null
      ? 'enabled'
      : 'unavailable';
  }
  if (snapshot.status === 'disabled') {
    return snapshot.enabled === false && snapshot.configured_enabled === false
      ? 'disabled'
      : 'unavailable';
  }
  if (snapshot.status === 'expired') {
    return snapshot.enabled === false && snapshot.configured_enabled === true
      ? 'expired'
      : 'unavailable';
  }
  return 'unavailable';
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function parseTimestamp(value: string | null) {
  if (!value) {
    return null;
  }
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? null : timestamp;
}

function formatTimestamp(value: string | null, locale: 'en' | 'zh') {
  const timestamp = parseTimestamp(value);
  if (timestamp === null) {
    return fallbackTimestamp(value);
  }
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(timestamp);
}

function fallbackTimestamp(value: string | null) {
  return value || '—';
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
