import { formatTimestamp } from '../../../shared/format';
import { ControlledActionZone } from '../../../shared/ui/workbench';
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
      <SettingsLiveServices controller={controller} />
    </>
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
