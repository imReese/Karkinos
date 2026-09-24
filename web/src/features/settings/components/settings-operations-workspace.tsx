import { useEffect, useState, type FormEvent } from 'react';

import { formatTimestamp } from '../../../shared/format';
import { ControlledActionZone } from '../../../shared/ui/workbench';
import {
  type BoardBuyPermissions,
  type BoardPermissionStatus,
  useBoardBuyPermissionsQuery,
  useUpdateBoardBuyPermissionsMutation,
} from '../api';
import { MarketRefreshButton } from '../settings-feature-boundary';
import type { SettingsPageController } from './settings-page-controller';
import {
  CapabilityRow,
  ManualTaskRow,
  RegisterRow,
  SettingsDisclosure,
} from './settings-view-primitives';

export function SettingsOperationsWorkspace({
  controller,
}: {
  controller: SettingsPageController;
}) {
  return (
    <>
      <SettingsDataSourceOperations controller={controller} />
      <SettingsBoardPermissions controller={controller} />
      <SettingsLiveServices controller={controller} />
    </>
  );
}

const BOARDS = ['chinext', 'star', 'beijing'] as const;

function SettingsBoardPermissions({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const { locale } = controller;
  const status = useBoardBuyPermissionsQuery();
  const update = useUpdateBoardBuyPermissionsMutation();
  const [boards, setBoards] = useState<BoardBuyPermissions['boards']>({
    chinext: 'unknown',
    star: 'unknown',
    beijing: 'unknown',
  });
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    if (status.data) setBoards(status.data.boards);
  }, [status.data]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!confirmed) return;
    await update.mutateAsync(boards);
    setConfirmed(false);
  };

  const names = {
    chinext: locale === 'zh' ? '创业板' : 'ChiNext',
    star: locale === 'zh' ? '科创板' : 'STAR',
    beijing: locale === 'zh' ? '北交所' : 'Beijing Exchange',
  };
  const options: Array<[BoardPermissionStatus, string]> = [
    ['unknown', locale === 'zh' ? '未核实' : 'Unknown'],
    ['disabled', locale === 'zh' ? '不可买入' : 'Cannot buy'],
    ['enabled', locale === 'zh' ? '可以买入' : 'Can buy'],
  ];

  return (
    <SettingsDisclosure
      testId="settings-board-permissions-disclosure"
      title={locale === 'zh' ? '账户板块权限' : 'Account board access'}
      detail={
        locale === 'zh'
          ? '请从券商账户核对。未核实或过期的权限会阻止相关买入候选。'
          : 'Check your broker account. Unknown or expired access blocks buy candidates.'
      }
    >
      <form onSubmit={submit} className="space-y-3 py-3">
        <p className="app-muted text-xs">
          {status.isError
            ? locale === 'zh'
              ? '账户权限记录读取失败'
              : 'Could not read the account access review'
            : status.data?.status === 'current'
              ? locale === 'zh'
                ? `已核实，有效至 ${status.data.expires_on}`
                : `Reviewed, valid through ${status.data.expires_on}`
              : locale === 'zh'
                ? '尚无有效的账户权限核实记录'
                : 'No current access review'}
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          {BOARDS.map((board) => (
            <label
              key={board}
              className="space-y-1 text-xs text-[var(--app-text)]"
            >
              <span className="font-semibold">{names[board]}</span>
              <select
                value={boards[board]}
                onChange={(event) =>
                  setBoards((current) => ({
                    ...current,
                    [board]: event.target.value as BoardPermissionStatus,
                  }))
                }
                className="w-full rounded border border-[var(--app-border)] bg-[var(--app-surface-0)] p-2"
              >
                {options.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
        <p className="app-muted text-xs">
          {locale === 'zh'
            ? '科创板买入目前仍会被阻断，因为下游计划尚未支持其交易单位。'
            : 'STAR buys remain blocked until the downstream plan supports its order quantity rule.'}
        </p>
        <label className="flex items-start gap-2 text-xs text-[var(--app-text)]">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            {locale === 'zh'
              ? '我已在券商账户核对以上权限；此设置只用于筛选候选，不授权交易。'
              : 'I checked these permissions in my broker account. This filters candidates and does not authorize trading.'}
          </span>
        </label>
        {update.isError ? (
          <p role="alert" className="text-xs text-[var(--app-danger-text)]">
            {locale === 'zh' ? '保存失败，请重试。' : 'Save failed. Try again.'}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={
            !confirmed || update.isPending || status.isLoading || status.isError
          }
          className="app-link text-xs font-semibold disabled:opacity-50"
        >
          {locale === 'zh' ? '保存权限核实' : 'Save access review'}
        </button>
      </form>
    </SettingsDisclosure>
  );
}

function SettingsDataSourceOperations({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const {
    capabilityRows,
    copy,
    fundNavCapabilityLabel,
    hasFundEstimate,
    isFundNavBlocked,
    latestFallbackQuote,
    manualTasks,
    manualTasksDone,
    permissionReason,
    providerName,
    setManualTasksDone,
  } = controller;
  return (
    <div className="min-w-0">
      <SettingsDisclosure
        testId="settings-data-source-disclosure"
        title={copy.settings.dataSourceOperations}
        detail={copy.settings.dataSourceOperationsDetail}
      >
        <section
          className="min-w-0 border-y border-[var(--app-divider)] py-3"
          data-settings-surface="operations-register"
        >
          <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
            <h3 className="text-sm font-semibold text-[var(--app-text)]">
              {copy.settings.providerCapabilityMatrix}
            </h3>
            <span className="app-muted text-xs">
              {copy.settings.currentProvider}: {providerName}
            </span>
          </div>
          <div className="mt-3 overflow-x-auto overscroll-x-contain">
            <div className="min-w-[34rem] divide-y divide-[var(--app-divider)]">
              {capabilityRows.map((row) => (
                <CapabilityRow
                  key={row.label}
                  label={row.label}
                  source={row.source}
                  status={row.status}
                  tone={row.tone}
                />
              ))}
            </div>
          </div>
        </section>

        <section className="min-w-0 border-y border-[var(--app-divider)] py-3">
          <h3 className="text-sm font-semibold text-[var(--app-text)]">
            {copy.settings.tusharePermissions}
          </h3>
          <div className="mt-2 grid gap-x-5 md:grid-cols-2">
            <RegisterRow
              label={fundNavCapabilityLabel}
              value={
                isFundNavBlocked
                  ? copy.settings.permissionBlocked
                  : copy.settings.permissionUnknown
              }
              tone={isFundNavBlocked ? 'danger' : 'warning'}
              ariaLabelPrefix="Capability"
            />
            <RegisterRow
              label={copy.settings.fundFallback}
              value={
                hasFundEstimate
                  ? copy.settings.eastmoneyFundEstimate
                  : copy.shell.statusUnknown
              }
              tone={hasFundEstimate ? 'success' : 'neutral'}
              ariaLabelPrefix="Capability"
            />
          </div>
          <p className="app-muted mt-2 text-xs leading-5">
            {permissionReason}
            {latestFallbackQuote?.timestamp
              ? ` · ${copy.settings.latestFallbackQuote}: ${formatTimestamp(
                  latestFallbackQuote.timestamp,
                )}`
              : ''}
          </p>
        </section>

        <section className="min-w-0 border-y border-[var(--app-divider)] py-3">
          <h3 className="text-sm font-semibold text-[var(--app-text)]">
            {copy.settings.manualDailyTaskChecklist}
          </h3>
          <div className="mt-2 divide-y divide-[var(--app-divider)]">
            {manualTasks.map((task) => (
              <ManualTaskRow
                key={task.id}
                label={task.label}
                href={task.href}
                actionLabel={copy.settings.openExternal}
                checked={Boolean(manualTasksDone[task.id])}
                onChange={(checked) =>
                  setManualTasksDone((current) => ({
                    ...current,
                    [task.id]: checked,
                  }))
                }
              />
            ))}
          </div>
        </section>

        <ControlledActionZone
          tone="info"
          title={copy.market.refreshQuotes}
          description={copy.settings.refreshActionDetail}
          evidence={copy.settings.refreshActionEvidence}
        >
          <MarketRefreshButton />
        </ControlledActionZone>
      </SettingsDisclosure>
    </div>
  );
}

function SettingsLiveServices({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const { boundaryRows, copy } = controller;
  return (
    <div className="min-w-0">
      <SettingsDisclosure
        testId="settings-live-services-disclosure"
        title={copy.settings.liveServices}
        detail={copy.settings.liveServicesDetail}
      >
        <div className="grid gap-x-4 border-y border-[var(--app-divider)] md:grid-cols-2">
          {boundaryRows.map((row) => (
            <RegisterRow
              key={row.label}
              label={row.label}
              value={row.value}
              tone={row.tone}
              ariaLabelPrefix="Boundary item"
            />
          ))}
        </div>
      </SettingsDisclosure>
    </div>
  );
}
