import type { Locale } from '../../shared/preferences/context';
import { observationCopy } from './copy-observations';

export const observationAutomationCopy = {
  en: {
    title: 'Automatic advance',
    scope:
      'Opt in separately for this observation. While the service is running, it checks about every 5 minutes and uses only complete, locally verified Datasets. It does not call data providers or grant account authority.',
    window:
      'Publication window: 16:00 after market close to 09:30 on the next trading day (Shanghai time). Missed windows are not backfilled.',
    data: 'Prepare and verify new Datasets through the existing data controls. Missing data waits; enabling this setting does not fetch it.',
    separate:
      'Turning automatic advance off does not pause the observation. Manual publication and measurement remain available; paused observations can still be measured manually.',
    enable: 'Enable automatic advance',
    disable: 'Disable automatic advance',
    saving: 'Saving automatic advance…',
    refresh: 'Refresh automatic advance state',
    unknown:
      'Automatic advance state is unavailable in this response. Refresh before changing it.',
    saved: 'Saved and reloaded the observation.',
    failed:
      'Could not confirm the saved state. Refresh before changing automatic advance again.',
    conflict:
      'This automatic advance setting changed elsewhere. Refresh its saved state; your change was not retried.',
    readFailed:
      'Could not load the latest automatic advance state. Refresh to retry.',
    pausedDetail:
      'This observation is paused. Automatic advance cannot be enabled; an existing setting can be turned off.',
    checked: 'Last automatic check',
    attempted: 'Last automatic advance attempt',
    decision: 'Decision session',
    dataset: 'Selected local Dataset',
    blocker: 'Saved blocker',
    diagnostics: 'Dataset discovery details',
    incomplete:
      'Dataset discovery is incomplete. Unreadable candidates are recorded below.',
    complete: 'This search encountered no unidentifiable candidates.',
    disabled: 'Automatic advance off',
    paused: 'Observation paused · automatic advance stopped',
    waiting: 'Waiting for data or the publication window',
    ready: 'Enabled · awaiting the next check',
    completed: 'Current decision session processed',
    blocked: 'Automatic advance blocked',
    missing:
      'No complete verified local Dataset is available. Prepare and verify the required data manually.',
    unreadable:
      'Local Dataset evidence could not be read or verified. Inspect the discovery details and prepare verified data.',
    missed:
      'The publication window was missed. Automatic advance will not publish for that missed session.',
    beforeClose: 'Waiting until 16:00 after the latest market close.',
    invalid:
      'The saved automatic advance policy is invalid. Refresh and inspect its saved state.',
    otherBlocker:
      'Automatic advance did not complete. The saved blocker code is available below.',
  },
  zh: {
    title: '自动推进',
    scope:
      '每条观察单独选择启用。服务运行时约每 5 分钟检查一次，只使用本地完整且已核验的 Dataset，不调用数据供应商，也不授予账户权限。',
    window:
      '发布窗口为收盘当日 16:00 至下一交易日 09:30（北京时间），错过窗口不会补发。',
    data: '新增 Dataset 仍须通过现有数据界面手动准备和核验。缺少数据时等待，打开开关不会自动获取数据。',
    separate:
      '关闭自动推进不等于暂停观察，手动发布和评估仍可用；已暂停观察仍可手动评估已有发布。',
    enable: '启用自动推进',
    disable: '关闭自动推进',
    saving: '正在保存自动推进设置…',
    refresh: '刷新自动推进状态',
    unknown: '此响应未提供自动推进状态，请先刷新再修改。',
    saved: '已保存并重新读取观察。',
    failed: '无法确认已保存状态，请先刷新再修改自动推进设置。',
    conflict:
      '自动推进设置已在其他会话更改，请刷新已保存状态。本次修改未自动重试。',
    readFailed: '无法读取最新自动推进状态，请刷新重试。',
    pausedDetail:
      '本观察已暂停，不能启用自动推进；已有的自动推进设置仍可关闭。',
    checked: '最近自动检查',
    attempted: '最近自动推进尝试',
    decision: '决策交易日',
    dataset: '选中的本地 Dataset',
    blocker: '已保存的阻断原因',
    diagnostics: 'Dataset 查找详情',
    incomplete: 'Dataset 查找尚不完整，无法读取的候选记录如下。',
    complete: '本次查找未遇到无法识别的候选。',
    disabled: '自动推进已关闭',
    paused: '观察已暂停 · 自动推进已停止',
    waiting: '等待数据或发布窗口',
    ready: '已启用 · 等待下一次检查',
    completed: '当前决策交易日已处理',
    blocked: '自动推进已阻断',
    missing: '暂无完整、已核验的本地 Dataset，请手动准备并核验所需数据。',
    unreadable: '本地 Dataset 证据无法读取或核验，请查看详情并准备已核验数据。',
    missed: '已错过发布窗口，自动推进不会补发该交易日。',
    beforeClose: '等待最近交易日收盘后的 16:00。',
    invalid: '已保存的自动推进策略无效，请刷新并检查其状态。',
    otherBlocker: '自动推进未完成，下方保留了已保存的阻断代码。',
  },
} as const;

export function automationBlocker(code: string, locale: Locale) {
  const labels = observationAutomationCopy[locale];
  if (code === 'observation_automation_dataset_missing') return labels.missing;
  if (code.includes('unreadable') || code.includes('catalog_mismatch'))
    return labels.unreadable;
  if (code === 'observation_automation_publication_window_missed')
    return labels.missed;
  if (code === 'observation_automation_waiting_after_close')
    return labels.beforeClose;
  if (code === 'observation_automation_policy_invalid') return labels.invalid;
  if (code === 'observation_code_changed')
    return observationCopy[locale].codeChanged;
  if (code.includes('calendar')) return observationCopy[locale].calendar;
  return labels.otherBlocker;
}
