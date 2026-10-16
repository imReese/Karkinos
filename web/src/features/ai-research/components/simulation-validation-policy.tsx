import type { SimulationValidationPolicy } from '../shadow-research-api';
import { Field } from './shadow-research-view';

const AUTHORIZE =
  'authorize_bounded_independent_research_simulation_without_account_publication_trade_or_capital_authority';

export function SimulationValidationSettings({
  value,
  defaults,
  locale,
  onChange,
}: {
  value: SimulationValidationPolicy | undefined;
  defaults: SimulationValidationPolicy | undefined;
  locale: string;
  onChange: (value: SimulationValidationPolicy) => void;
}) {
  const zh = locale === 'zh';
  const draft = value ?? defaults;
  if (!draft) return null;
  const update = (patch: Partial<SimulationValidationPolicy>) =>
    onChange({ ...draft, ...patch });

  return (
    <div className="mt-4 border-t border-[var(--app-divider)] pt-4">
      <label className="flex min-h-11 w-fit items-center gap-2 text-sm font-semibold text-[var(--app-text)]">
        <input
          type="checkbox"
          checked={value?.enabled ?? false}
          onChange={(event) =>
            update({ enabled: event.target.checked, authorization: AUTHORIZE })
          }
        />
        {zh
          ? '自动启动独立前向验证'
          : 'Start independent forward validation automatically'}
      </label>
      <p className="text-xs leading-5 text-[var(--app-muted)]">
        {zh
          ? '使用完整声明市场数据，在独立模拟账户中验证冻结策略；账户发布授权单独设置。费用采用冻结的研究假设。'
          : 'Validate the frozen strategy on the declared market in an independent simulated book. Account publication has separate authorization. Costs use frozen research assumptions.'}
      </p>
      {value?.enabled ? (
        <>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Field
              label={zh ? '模拟资金（元）' : 'Simulated capital (CNY)'}
              type="number"
              value={String(draft.initial_cash ?? '')}
              onChange={(initial_cash) => update({ initial_cash })}
            />
            <Field
              label={zh ? '最终验证检查日' : 'Final evaluation checkpoint'}
              type="date"
              value={draft.statistical_policy?.decision_checkpoint ?? ''}
              onChange={(decision_checkpoint) =>
                update({
                  statistical_policy: {
                    ...draft.statistical_policy,
                    decision_checkpoint,
                  },
                })
              }
            />
            <Field
              label={zh ? '验证授权有效至' : 'Validation authorization expires'}
              type="date"
              value={draft.expires_at?.slice(0, 10) ?? ''}
              onChange={(date) =>
                update({ expires_at: date ? `${date}T23:59:59+08:00` : '' })
              }
            />
          </div>
          <p className="mt-2 text-xs leading-5 text-[var(--app-muted)]">
            {zh
              ? `至少积累 ${draft.statistical_policy?.minimum_observations ?? 60} 个真实未来观测；数据就绪后冻结窗口，届时检查净超额收益及风险。暂停会停止新的验证操作，保留已有记录。`
              : `Collect at least ${draft.statistical_policy?.minimum_observations ?? 60} actual future observations. Freeze the window after inputs are ready, then evaluate net excess return and risk at the checkpoint. Pausing retains existing records.`}
          </p>
        </>
      ) : null}
    </div>
  );
}
