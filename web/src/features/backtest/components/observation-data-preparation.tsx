import { formatTimestamp } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import type { ObservationAutomation } from '../observation-contracts';

export function ObservationDataPreparation({
  preparation,
  disabled,
  onToggle,
}: {
  preparation: NonNullable<ObservationAutomation['dataset_preparation']>;
  disabled: boolean;
  onToggle: () => void;
}) {
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const states: Record<string, string> = {
    ready: zh ? '等待检查' : 'Awaiting check',
    waiting: zh ? '等待核验任务' : 'Waiting for verification jobs',
    completed: zh ? '数据已准备' : 'Data ready',
    blocked: zh ? '数据准备阻断' : 'Data preparation blocked',
    disabled: zh ? '未自动准备' : 'No automatic preparation',
  };
  return (
    <div className="space-y-2 border-t border-[var(--app-divider)] pt-3">
      <h5 className="font-semibold">
        {zh ? '观察数据自动准备' : 'Automatic observation data preparation'}
      </h5>
      <p className="app-muted">
        {zh
          ? '单独授权数据服务为冻结的标的篮子提交双源核验任务并发布完整 Dataset。使用现有供应商预算，缺少或冲突的数据会等待；不会改写历史输入、补发目标或授予账户权限。'
          : 'Separate permission for the data service to verify the frozen basket with two sources and publish complete Datasets. Existing provider budgets apply. Missing or conflicting data waits; historical inputs, targets and account authority are preserved.'}
      </p>
      <p className="app-muted">
        {zh
          ? '最多 32 个标的、从原始起点起不超过 366 个日历日。需要数据工作进程运行；自动发布目标和账本结算需分别启用。观察暂停后，仅在账本自动结算仍启用时继续供数以估值持仓。'
          : 'Up to 32 instruments and 366 calendar days from the original start. The data worker must be running. Target publication and paper settlement require their own settings. After observation pause, data supply continues only with paper settlement enabled, to value retained holdings.'}
      </p>
      <p role="status">{states[preparation.status] ?? preparation.status}</p>
      <button
        type="button"
        className="app-button-secondary min-h-11 px-3 py-2 disabled:opacity-50"
        disabled={disabled}
        onClick={onToggle}
      >
        {preparation.enabled
          ? zh
            ? '关闭观察数据自动准备'
            : 'Disable automatic data preparation'
          : zh
            ? '启用观察数据自动准备'
            : 'Enable automatic data preparation'}
      </button>
      {preparation.last_checked_at ? (
        <p>
          {zh ? '最近数据检查' : 'Last data check'}:{' '}
          {formatTimestamp(preparation.last_checked_at)}
        </p>
      ) : null}
      {preparation.through_session ? (
        <p>
          {zh ? '准备至交易日' : 'Through session'}:{' '}
          {preparation.through_session}
        </p>
      ) : null}
      {preparation.last_blocker ||
      preparation.dataset_id ||
      preparation.job_ids.length ? (
        <details>
          <summary className="cursor-pointer">
            {zh ? '数据准备详情' : 'Data preparation details'}
          </summary>
          <div className="mt-2 space-y-1 break-all font-mono">
            {preparation.last_blocker ? (
              <p>{preparation.last_blocker.code}</p>
            ) : null}
            {preparation.dataset_id ? <p>{preparation.dataset_id}</p> : null}
            {preparation.job_ids.map((id) => (
              <p key={id}>{id}</p>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}
