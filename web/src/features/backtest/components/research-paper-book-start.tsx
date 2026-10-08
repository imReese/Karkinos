import { useState } from 'react';
import { usePreferences } from '../../../shared/preferences/context';
import { paperBookCopy } from '../copy-paper-book';
import type { ResearchObservation } from '../observation-contracts';
import type {
  PaperBookCommand,
  PaperHealthPolicy,
} from '../paper-book-contracts';
import { BacktestCostControls } from './backtest-cost-controls';
import { useBacktestCostInputs } from './backtest-cost-inputs';
const fieldClass = 'app-field min-h-11 w-full min-w-0 px-3 py-2';
const buttonClass =
  'app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2 text-xs disabled:opacity-50';
export function ResearchPaperBookStart({
  observation,
  blocked,
  saving,
  onCreate,
}: {
  observation: ResearchObservation;
  blocked: boolean;
  saving: boolean;
  onCreate: (
    payload: Omit<
      Extract<PaperBookCommand, { kind: 'create' }>['payload'],
      'request_id'
    >,
  ) => void;
}) {
  const { locale } = usePreferences();
  const labels = paperBookCopy[locale];
  const costs = useBacktestCostInputs();
  const [initialCash, setInitialCash] = useState('');
  const [healthEnabled, setHealthEnabled] = useState(false);
  const [healthMode, setHealthMode] =
    useState<PaperHealthPolicy['mode']>('report_only');
  const [healthSessions, setHealthSessions] = useState('25');
  const [healthDrawdown, setHealthDrawdown] = useState('10');
  const [healthExcess, setHealthExcess] = useState('0');
  const healthValid =
    /^\d+$/.test(healthSessions) &&
    Number(healthSessions) >= 1 &&
    Number(healthSessions) <= 2000 &&
    healthDrawdown.trim() !== '' &&
    Number.isFinite(Number(healthDrawdown)) &&
    Number(healthDrawdown) >= 0 &&
    Number(healthDrawdown) <= 100 &&
    healthExcess.trim() !== '' &&
    Number.isFinite(Number(healthExcess)) &&
    Number(healthExcess) >= -100 &&
    Number(healthExcess) <= 100;
  const supported =
    observation.universe.length > 0 &&
    observation.universe.every((item) =>
      ['stock', 'etf'].includes(item.instrument_type),
    );
  const validCash =
    /^\d+(?:\.\d+)?$/.test(initialCash.trim()) &&
    Number.isFinite(Number(initialCash)) &&
    Number(initialCash) > 0;
  return (
    <div className="min-w-0 space-y-3">
      <p className="app-muted text-xs leading-5">{labels.createHint}</p>
      {!supported ? (
        <p className="text-xs leading-5">{labels.unsupported}</p>
      ) : null}
      <label className="grid max-w-sm gap-2 text-xs">
        {labels.initialCash}
        <input
          className={fieldClass}
          type="text"
          inputMode="decimal"
          value={initialCash}
          disabled={blocked || !supported}
          onChange={(event) => setInitialCash(event.target.value)}
        />
      </label>
      <BacktestCostControls
        inputs={costs}
        disabled={blocked || !supported}
        description={labels.costs}
        defaultDescription={labels.defaultCosts}
        fields={[
          ...(observation.universe.some(
            (item) => item.instrument_type === 'stock',
          )
            ? (['stock_commission_rate', 'stock_min_commission'] as const)
            : []),
          ...(observation.universe.some(
            (item) => item.instrument_type === 'etf',
          )
            ? (['etf_commission_rate', 'etf_min_commission'] as const)
            : []),
          'slippage_bps',
          'max_volume_participation',
        ]}
      />
      <fieldset className="space-y-3 text-xs" disabled={blocked || !supported}>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={healthEnabled}
            onChange={(event) => setHealthEnabled(event.target.checked)}
          />
          {locale === 'zh'
            ? '冻结模拟健康规则（可选）'
            : 'Freeze modeled book health rules (optional)'}
        </label>
        {healthEnabled ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-2">
              {locale === 'zh' ? '越界后的动作' : 'Action on breach'}
              <select
                className={fieldClass}
                value={healthMode}
                onChange={(event) =>
                  setHealthMode(event.target.value as PaperHealthPolicy['mode'])
                }
              >
                <option value="report_only">
                  {locale === 'zh' ? '仅提示复核' : 'Report for review'}
                </option>
                <option value="pause_on_breach">
                  {locale === 'zh'
                    ? '停止接收模拟目标'
                    : 'Stop paper target intake'}
                </option>
              </select>
            </label>
            {[
              [
                locale === 'zh'
                  ? '最少有效结算日'
                  : 'Minimum eligible settled sessions',
                healthSessions,
                setHealthSessions,
              ],
              [
                locale === 'zh' ? '最大回撤（%）' : 'Maximum drawdown (%)',
                healthDrawdown,
                setHealthDrawdown,
              ],
              [
                locale === 'zh'
                  ? '最低模拟净超额（%）'
                  : 'Minimum modeled net excess (%)',
                healthExcess,
                setHealthExcess,
              ],
            ].map(([label, value, setter]) => (
              <label className="grid gap-2" key={String(label)}>
                {String(label)}
                <input
                  className={fieldClass}
                  inputMode="decimal"
                  value={String(value)}
                  onChange={(event) =>
                    (setter as (value: string) => void)(event.target.value)
                  }
                />
              </label>
            ))}
          </div>
        ) : null}
        <p className="app-muted">
          {locale === 'zh'
            ? '规则创建后冻结，仅影响模拟目标接收；不清仓，不改变资格或账户权限。'
            : 'Rules are frozen at creation and affect paper target intake only. They do not liquidate positions or change qualification or account authority.'}
        </p>
      </fieldset>
      <button
        type="button"
        className={buttonClass}
        disabled={
          blocked ||
          !supported ||
          !validCash ||
          !costs.valid ||
          (healthEnabled && !healthValid)
        }
        onClick={() => {
          const payload = {
            initial_cash: initialCash.trim(),
            ...(healthEnabled
              ? {
                  health_policy: {
                    mode: healthMode,
                    minimum_settled_sessions: Number(healthSessions),
                    maximum_drawdown: String(Number(healthDrawdown) / 100),
                    minimum_net_excess_return: String(
                      Number(healthExcess) / 100,
                    ),
                  },
                }
              : {}),
            ...(costs.assumptions
              ? { cost_assumptions: costs.assumptions }
              : {}),
          };
          onCreate(payload);
        }}
      >
        {saving ? labels.saving : labels.create}
      </button>
    </div>
  );
}
