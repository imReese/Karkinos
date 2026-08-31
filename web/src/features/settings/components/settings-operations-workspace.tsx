import { formatTimestamp } from '../../../shared/format';
import { ControlledActionZone } from '../../../shared/ui/workbench';
import { MarketRefreshButton } from '../settings-feature-boundary';
import type { SettingsPageController } from './settings-page-controller';
import {
  CapabilityRow,
  ManualTaskRow,
  RegisterRow,
  SettingsDisclosure,
  StatusMetric,
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
    <div className="order-3 min-w-0 xl:col-start-2 xl:row-start-2">
      <SettingsDisclosure
        testId="settings-data-source-disclosure"
        title={copy.settings.dataSourceOperations}
        detail={copy.settings.dataSourceOperationsDetail}
      >
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
          <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm font-semibold">
                {copy.settings.providerCapabilityMatrix}
              </div>
              <div className="app-muted text-xs">
                {copy.settings.currentProvider}: {providerName}
              </div>
            </div>
            <div className="mt-4 overflow-x-auto">
              <div className="min-w-[34rem] divide-y divide-[color-mix(in_srgb,var(--app-border)_18%,transparent)]">
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
          </div>

          <div className="grid min-w-0 gap-4">
            <div className="rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
              <div className="text-sm font-semibold">
                {copy.settings.tusharePermissions}
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                <StatusMetric
                  label={fundNavCapabilityLabel}
                  value={
                    isFundNavBlocked
                      ? copy.settings.permissionBlocked
                      : copy.settings.permissionUnknown
                  }
                  tone={isFundNavBlocked ? 'danger' : 'warning'}
                />
                <StatusMetric
                  label={copy.settings.fundFallback}
                  value={
                    hasFundEstimate
                      ? copy.settings.eastmoneyFundEstimate
                      : copy.shell.statusUnknown
                  }
                  tone={hasFundEstimate ? 'success' : 'neutral'}
                />
              </div>
              <div className="app-muted mt-3 text-xs leading-5">
                {permissionReason}
                {latestFallbackQuote?.timestamp
                  ? ` · ${copy.settings.latestFallbackQuote}: ${formatTimestamp(
                      latestFallbackQuote.timestamp,
                    )}`
                  : ''}
              </div>
            </div>

            <div className="rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
              <div className="text-sm font-semibold">
                {copy.settings.manualDailyTaskChecklist}
              </div>
              <div className="mt-3 grid gap-2">
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
            </div>
          </div>
        </div>

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
    <div className="order-4 min-w-0 xl:col-start-2 xl:row-start-3">
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
