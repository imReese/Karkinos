import { formatTimestamp } from '../../../shared/format';
import {
  usePreferences,
  type Locale,
} from '../../../shared/preferences/context';
import {
  formatPublicEvidenceReference,
  formatPublicOperationalNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  EvidenceState,
  StatusBadge as WorkbenchStatusBadge,
} from '../../../shared/ui/workbench';
import type {
  BrokerAdapterReadiness,
  BrokerConnectorSoakPromotionStatus,
} from '../operations-boundary';

export function BrokerAdapterReadinessPanel({
  readiness,
  loading,
  error,
  soak,
  soakLoading,
  soakError,
}: {
  readiness: BrokerAdapterReadiness | null;
  loading: boolean;
  error: boolean;
  soak: BrokerConnectorSoakPromotionStatus | null;
  soakLoading: boolean;
  soakError: boolean;
}) {
  const { locale } = usePreferences();
  const latest = readiness?.latest_release ?? null;
  const status = readiness?.status ?? 'not_configured';
  const copy = brokerAdapterReadinessCopy(locale);
  const statusLabel = copy.status[status] ?? formatPublicStatus(status, locale);
  const statusTone =
    error || readiness?.subsystem_status === 'blocked'
      ? 'danger'
      : readiness?.subsystem_status === 'manual_action_required' ||
          readiness?.subsystem_status === 'degraded'
        ? 'warning'
        : 'neutral';
  const matchedSoak = selectSoakPromotionConnector(
    soak,
    latest?.collector_id ?? '',
  );
  const operational = matchedSoak?.operational_evidence;
  const phaseCoverage = ['startup', 'intraday', 'end_of_day'].map(
    (phase) => operational?.phase_coverage[phase] ?? [],
  );
  const drillCoverage = [
    'disconnect',
    'schema_drift',
    'stale_data',
    'duplicate_evidence',
    'restart_recovery',
  ].map((drill) => operational?.drill_coverage[drill] === true);
  const soakBlockers = matchedSoak?.promotion_blockers ?? [];
  const soakStatus = soakLoading
    ? copy.loading
    : soakError
      ? copy.unavailable
      : matchedSoak?.promotion_ready
        ? copy.soakReady
        : matchedSoak
          ? copy.soakReviewRequired
          : copy.soakNotConfigured;
  const soakTone = soakError
    ? 'danger'
    : matchedSoak?.promotion_ready
      ? 'success'
      : matchedSoak
        ? 'warning'
        : 'neutral';

  return (
    <section
      className="app-workbench-section min-w-0"
      data-testid="broker-adapter-readiness"
    >
      <div className="min-w-0 px-1 py-4 sm:px-3">
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{copy.kicker}</div>
            <h2 className="app-card-title mt-1.5">{copy.title}</h2>
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {copy.detail}
            </p>
          </div>
          <WorkbenchStatusBadge className="w-fit shrink-0" tone={statusTone}>
            {loading ? copy.loading : error ? copy.unavailable : statusLabel}
          </WorkbenchStatusBadge>
        </div>

        {error ? (
          <div className="app-error-text mt-4 text-sm" role="alert">
            {copy.loadFailed}
          </div>
        ) : loading ? (
          <div className="app-muted mt-4 text-sm">{copy.loading}</div>
        ) : !readiness || status === 'not_configured' ? (
          <EvidenceState
            className="mt-4"
            kind="empty"
            title={copy.notConfiguredTitle}
            description={copy.notConfigured}
          />
        ) : (
          <div className="mt-4 min-w-0">
            {latest?.release_evidence_ref ? (
              <div className="app-muted mb-3 min-w-0 truncate text-xs">
                {copy.releaseEvidence}{' '}
                <span title={latest.release_evidence_ref}>
                  {formatPublicEvidenceReference(
                    latest.release_evidence_ref,
                    locale,
                  )}
                </span>
              </div>
            ) : null}
            <div className="grid min-w-0 gap-x-4 sm:grid-cols-2 lg:grid-cols-4">
              <BrokerReadinessMetric
                label={copy.provider}
                value={latest?.provider || '--'}
              />
              <BrokerReadinessMetric
                label={copy.releaseReview}
                value={formatPublicStatus(latest?.review_status, locale)}
              />
              <BrokerReadinessMetric
                label={copy.conformance}
                value={formatPublicStatus(latest?.conformance_status, locale)}
              />
              <BrokerReadinessMetric
                label={copy.collector}
                value={formatPublicStatus(latest?.collector_status, locale)}
              />
            </div>
          </div>
        )}

        {!loading && !error && readiness?.blockers.length ? (
          <div className="mt-4 border-l-2 border-[var(--app-warning-indicator)] py-1 pl-3 text-sm text-[var(--app-text-secondary)]">
            <div className="font-semibold text-[var(--app-text)]">
              {copy.blockers(readiness.blockers.length)}
            </div>
            <ul className="mt-2 grid gap-1 pl-5">
              {readiness.blockers.slice(0, 3).map((blocker) => (
                <li className="list-disc break-words" key={blocker}>
                  {formatPublicOperationalNote(blocker, locale)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {!loading && !error && readiness && status !== 'not_configured' ? (
          <div className="mt-4 grid min-w-0 gap-2 border-t border-[var(--app-divider)] pt-3 text-sm sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
            <div className="min-w-0 break-words text-[var(--app-text-secondary)]">
              <span className="font-semibold text-[var(--app-text)]">
                {copy.nextAction}
              </span>{' '}
              {formatPublicOperationalNote(
                readiness.next_manual_action,
                locale,
              )}
            </div>
            <div className="shrink-0 text-xs text-[var(--app-muted)]">
              {latest?.collector_updated_at
                ? `${copy.lastEvidence} ${formatTimestamp(latest.collector_updated_at)}`
                : copy.noCollectorRun}
            </div>
          </div>
        ) : null}

        <section
          className="mt-5 border-t border-[var(--app-divider)] pt-4"
          data-testid="broker-soak-promotion-readiness"
        >
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-[var(--app-text)]">
                {copy.soakTitle}
              </h3>
              <p className="app-muted mt-1 text-xs leading-5">
                {copy.soakDetail}
              </p>
            </div>
            <WorkbenchStatusBadge className="w-fit shrink-0" tone={soakTone}>
              {soakStatus}
            </WorkbenchStatusBadge>
          </div>

          <div className="mt-3 grid min-w-0 gap-x-4 sm:grid-cols-2 xl:grid-cols-5">
            <BrokerReadinessMetric
              label={copy.soakDays}
              value={
                operational
                  ? `${operational.selected_trading_day_count}/${operational.target_trading_day_count}`
                  : '--'
              }
            />
            <BrokerReadinessMetric
              label={copy.soakPhases}
              value={
                operational
                  ? `${phaseCoverage.filter((days) => days.length >= operational.target_trading_day_count).length}/${phaseCoverage.length}`
                  : '--'
              }
            />
            <BrokerReadinessMetric
              label={copy.soakDrills}
              value={
                operational
                  ? `${drillCoverage.filter(Boolean).length}/${drillCoverage.length}`
                  : '--'
              }
            />
            <BrokerReadinessMetric
              label={copy.accountTruthBinding}
              value={
                matchedSoak?.account_truth_reconciliation_linked
                  ? copy.accountTruthLinked
                  : matchedSoak
                    ? copy.accountTruthMissing
                    : '--'
              }
            />
            <BrokerReadinessMetric
              label={copy.ownerAcceptance}
              value={
                matchedSoak?.owner_acceptance_recorded
                  ? copy.ownerAcceptanceRecorded
                  : matchedSoak
                    ? copy.ownerAcceptanceMissing
                    : '--'
              }
            />
          </div>

          {!soakLoading && !soakError && soakBlockers.length ? (
            <div className="mt-3 border-l-2 border-[var(--app-warning-indicator)] py-1 pl-3 text-xs leading-5 text-[var(--app-text-secondary)]">
              {copy.soakBlockers(soakBlockers.length)}{' '}
              {soakBlockers
                .slice(0, 2)
                .map((blocker) => formatPublicOperationalNote(blocker, locale))
                .join(' · ')}
            </div>
          ) : null}
        </section>

        <p className="app-muted mt-3 text-xs leading-5">{copy.boundary}</p>
      </div>
    </section>
  );
}

function selectSoakPromotionConnector(
  status: BrokerConnectorSoakPromotionStatus | null,
  collectorId: string,
) {
  if (!status?.connectors.length) {
    return null;
  }
  const exact = status.connectors.find(
    (connector) => connector.connector_id === collectorId,
  );
  if (exact) {
    return exact;
  }
  return !collectorId && status.connectors.length === 1
    ? status.connectors[0]
    : null;
}

function BrokerReadinessMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0 border-t border-[var(--app-divider)] py-2.5">
      <div className="text-xs font-medium text-[var(--app-text-secondary)]">
        {label}
      </div>
      <div
        className="mt-0.5 truncate text-sm font-semibold text-[var(--app-text)]"
        title={value}
      >
        {value || '--'}
      </div>
    </div>
  );
}

function brokerAdapterReadinessCopy(locale: Locale) {
  if (locale === 'zh') {
    return {
      kicker: '只读账户事实',
      title: '券商适配器证据',
      detail:
        '统一查看放行凭证、确定性一致性验证与采集器运行证据；这里不会注册或连接券商。',
      loading: '读取中',
      unavailable: '不可用',
      loadFailed: '券商适配器证据读取失败；未改变任何交易或资本权限。',
      notConfiguredTitle: '未选择券商环境',
      notConfigured:
        '尚未选择或授权真实券商环境。Karkinos 保持无默认适配器、无提交与撤单权限。',
      provider: '来源标识',
      releaseEvidence: '放行证据：',
      releaseReview: '放行审查',
      conformance: '一致性验证',
      collector: '采集器证据',
      soakTitle: '只读券商试运行门禁',
      soakDetail:
        '核对 20 个交易日、每日三阶段、恢复演练、账户事实与已签名的所有者验收；这里只展示证据，不执行启用。',
      soakDays: '合格交易日',
      soakPhases: '运行阶段',
      soakDrills: '恢复演练',
      accountTruthBinding: '账户事实',
      accountTruthLinked: '已绑定并通过',
      accountTruthMissing: '尚未绑定通过',
      ownerAcceptance: '所有者验收',
      ownerAcceptanceRecorded: '签名验收已记录',
      ownerAcceptanceMissing: '等待签名验收',
      soakReady: '证据齐备，仍无执行权限',
      soakReviewRequired: '证据未齐，需复核',
      soakNotConfigured: '尚无只读试运行证据',
      soakBlockers: (count: number) => `${count} 项试运行阻断：`,
      nextAction: '下一步：',
      lastEvidence: '最近证据',
      noCollectorRun: '尚无采集器运行',
      blockers: (count: number) => `${count} 项证据阻断`,
      boundary:
        '第三方适配器仍需单独审查和用户显式授权；本视图只读持久化证据，不联系外部服务，不修改订单状态、账本、风控、紧急停止或资本授权。',
      status: {
        not_configured: '未配置',
        review_required: '等待人工审查',
        evidence_attention_required: '证据需复核',
        evidence_ready_not_activated: '证据已通过，未启用',
        observing_readonly: '只读证据采集中',
      } as Record<string, string>,
    };
  }
  return {
    kicker: 'Read-only account truth',
    title: 'Broker adapter evidence',
    detail:
      'Review release, deterministic conformance, and collector-run evidence in one place; this surface never registers or contacts a broker.',
    loading: 'Loading',
    unavailable: 'Unavailable',
    loadFailed:
      'Broker adapter evidence could not be read; no trading or capital authority changed.',
    notConfiguredTitle: 'No broker environment selected',
    notConfigured:
      'No real broker environment has been selected or authorized. Karkinos retains no default adapter and no submit or cancel permission.',
    provider: 'Source label',
    releaseEvidence: 'Release evidence:',
    releaseReview: 'Release review',
    conformance: 'Conformance',
    collector: 'Collector evidence',
    soakTitle: 'Read-only broker pilot gate',
    soakDetail:
      'Verify 20 trading days, all daily phases, recovery drills, Account Truth, and signed owner acceptance. This surface displays evidence and never performs promotion.',
    soakDays: 'Qualified days',
    soakPhases: 'Run phases',
    soakDrills: 'Recovery drills',
    accountTruthBinding: 'Account Truth',
    accountTruthLinked: 'Linked and clear',
    accountTruthMissing: 'Not linked and clear',
    ownerAcceptance: 'Owner acceptance',
    ownerAcceptanceRecorded: 'Signed acceptance recorded',
    ownerAcceptanceMissing: 'Signed acceptance missing',
    soakReady: 'Evidence complete, authority still disabled',
    soakReviewRequired: 'Evidence incomplete, review required',
    soakNotConfigured: 'No read-only soak evidence',
    soakBlockers: (count: number) =>
      `${count} soak blocker${count === 1 ? ':' : 's:'}`,
    nextAction: 'Next: ',
    lastEvidence: 'Latest evidence',
    noCollectorRun: 'No collector run',
    blockers: (count: number) =>
      `${count} evidence blocker${count === 1 ? '' : 's'}`,
    boundary:
      'A third-party adapter still requires separate review and explicit owner authorization. This view reads persisted evidence only and does not mutate OMS, ledger, risk, kill switch, or capital authority.',
    status: {
      not_configured: 'Not configured',
      review_required: 'Human review required',
      evidence_attention_required: 'Evidence needs review',
      evidence_ready_not_activated: 'Evidence clear, not activated',
      observing_readonly: 'Observing read-only evidence',
    } as Record<string, string>,
  };
}
