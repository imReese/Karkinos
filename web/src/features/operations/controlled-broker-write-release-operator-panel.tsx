import { useState } from 'react';

import {
  useControlledBrokerWriteReleasesQuery,
  useControlledBrokerWriteReleaseStatusQuery,
  type BrokerAdapterReadiness,
  type BrokerConnectorSoakPromotionStatus,
} from './api';
import {
  mutationError,
  type Locale,
} from './controlled-broker-write-release/contracts';
import { IssueWriteReleaseFlow } from './controlled-broker-write-release/issue-flow';
import { RevokeWriteReleaseFlow } from './controlled-broker-write-release/revocation-flow';

export function ControlledBrokerWriteReleaseOperatorPanel({
  locale,
  readiness,
  soak,
}: {
  locale: Locale;
  readiness: BrokerAdapterReadiness | null;
  soak: BrokerConnectorSoakPromotionStatus | null;
}) {
  const [open, setOpen] = useState(false);
  const status = useControlledBrokerWriteReleaseStatusQuery(open);
  const releases = useControlledBrokerWriteReleasesQuery(open);

  return (
    <section
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
      data-testid="controlled-broker-write-release-panel"
    >
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">
              {locale === 'zh'
                ? '执行边缘能力门禁'
                : 'Execution-edge capability gate'}
            </div>
            <h2 className="app-card-title mt-1.5">
              {locale === 'zh'
                ? '签名式券商写入放行'
                : 'Signed broker write-edge release'}
            </h2>
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {locale === 'zh'
                ? '把严格 execution manifest、最新只读 release、已签名 soak acceptance 与所有者复核引用冻结为最长 12 小时的 manual_each_order 能力放行。该放行只是逐单提交的必要条件，不注册 gateway，不授予订单或资本权限。'
                : 'Freeze a strict execution manifest, newest read-only release, signed soak acceptance, and owner-review references into an at-most-12-hour manual_each_order capability release. It is necessary for a later per-order submission but registers no gateway and grants no order or capital authority.'}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <span className="app-chip">
              {!open
                ? locale === 'zh'
                  ? '复核已关闭'
                  : 'Review closed'
                : status.isLoading
                  ? locale === 'zh'
                    ? '读取中'
                    : 'Loading'
                  : status.isError
                    ? locale === 'zh'
                      ? '状态不可用'
                      : 'Status unavailable'
                    : status.data?.active_release_count
                      ? locale === 'zh'
                        ? `${status.data.active_release_count} 个当前放行`
                        : `${status.data.active_release_count} current ${
                            status.data.active_release_count === 1
                              ? 'release'
                              : 'releases'
                          }`
                      : locale === 'zh'
                        ? '无当前放行'
                        : 'No current release'}
            </span>
            <button
              type="button"
              className="app-button-secondary min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
              onClick={() => setOpen((value) => !value)}
            >
              {open
                ? locale === 'zh'
                  ? '关闭'
                  : 'Close'
                : locale === 'zh'
                  ? '打开能力复核'
                  : 'Open capability review'}
            </button>
          </div>
        </div>

        <div className="mt-3 flex min-w-0 flex-wrap gap-2 text-xs">
          <span className="app-chip">
            {locale === 'zh'
              ? '仅限逐单人工复核'
              : 'Per-order manual review only'}
          </span>
          <span className="app-chip">
            {locale === 'zh'
              ? '券商网关注册：已禁用'
              : 'Gateway registration: disabled'}
          </span>
          <span className="app-chip">
            {locale === 'zh'
              ? '资本权限：未改变'
              : 'Capital authority: unchanged'}
          </span>
        </div>

        {open && status.isError ? (
          <div className="app-error-text mt-3 text-sm" role="alert">
            {mutationError(status.error)}
          </div>
        ) : null}

        {open ? (
          <div className="mt-4 grid min-w-0 gap-4 border-t border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] pt-4 xl:grid-cols-2">
            <IssueWriteReleaseFlow
              locale={locale}
              readiness={readiness}
              soak={soak}
            />
            <RevokeWriteReleaseFlow
              locale={locale}
              releases={releases.data ?? []}
              loading={releases.isLoading}
              error={releases.isError ? mutationError(releases.error) : ''}
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}
