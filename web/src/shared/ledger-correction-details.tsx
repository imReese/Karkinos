import { formatCurrency, formatQuantity, formatTimestamp } from './format';
import type { PublicLedgerEntry } from './ledger-format-contracts';
import { isLedgerCorrection } from './ledger-format-values';
import type { Locale } from './locale';

export function LedgerEntryTime({
  entry,
  locale,
}: {
  entry: PublicLedgerEntry;
  locale: Locale;
}) {
  if (!isLedgerCorrection(entry))
    return <>{formatTimestamp(entry.timestamp)}</>;
  return (
    <>
      <div>
        {locale === 'zh' ? '记录于' : 'Recorded at'}{' '}
        {formatCorrectionTimestamp(entry.created_at, locale)}
      </div>
      <div>
        {locale === 'zh' ? '账本生效于' : 'Ledger effective at'}{' '}
        {formatCorrectionTimestamp(entry.timestamp, locale)}
      </div>
    </>
  );
}

export function LedgerCorrectionDetails({
  entry,
  locale,
}: {
  entry: PublicLedgerEntry;
  locale: Locale;
}) {
  if (!isLedgerCorrection(entry)) return null;
  const zh = locale === 'zh';
  const payload = entry.correction_payload;
  const evidence = entry.correction_evidence;
  const verified =
    payload?.schema_version ===
      'karkinos.legacy_fund_trade_duplicate_correction_plan.v1' &&
    evidence?.status === 'verified' &&
    evidence.blockers.length === 0 &&
    !!entry.entry_fingerprint &&
    evidence.entry_fingerprint === entry.entry_fingerprint;
  const number = (value: unknown) => {
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    if (typeof value === 'string' && !value.trim()) return null;
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  };
  const state = (key: string) => {
    const value = payload?.[key];
    return value && typeof value === 'object'
      ? (value as Record<string, unknown>)
      : {};
  };
  const before = state('position_before');
  const after = state('position_after');
  const changes = [
    [
      zh ? '账面现金' : 'Ledger cash',
      formatCurrency(number(payload?.cash_before)),
      formatCurrency(number(payload?.cash_after)),
    ],
    [
      zh ? '份额' : 'Quantity',
      formatQuantity(number(before.quantity)),
      formatQuantity(number(after.quantity)),
    ],
    [
      zh ? '平均成本' : 'Average cost',
      formatCurrency(number(before.avg_cost)),
      formatCurrency(number(after.avg_cost)),
    ],
    [
      zh ? '累计已实现盈亏' : 'Accumulated realized P/L',
      formatCurrency(number(before.realized_pnl)),
      formatCurrency(number(after.realized_pnl)),
    ],
  ];
  return (
    <details className="mt-2 min-w-0 text-xs break-words [overflow-wrap:anywhere]">
      <summary className="cursor-pointer font-semibold">
        {zh ? '查看修正依据' : 'View correction evidence'}
      </summary>
      <p className="mt-2" role="status">
        {verified
          ? zh
            ? '关联原流水与修正内容已核验；不代表历史收益或授权已核验。'
            : 'Referenced entries and correction content verified; historical returns and authorization are not verified.'
          : zh
            ? '修正证据待核验'
            : 'Correction evidence requires review'}
      </p>
      <p className="mt-2">
        {typeof payload?.authorization_fingerprint === 'string' &&
        payload.authorization_fingerprint
          ? zh
            ? '有授权摘要，未核验批准人／批准时间。'
            : 'Authorization digest recorded; approver and approval time are not verified.'
          : zh
            ? '未提供可核验的授权详情。'
            : 'Verifiable authorization details are unavailable.'}
      </p>
      {verified && (
        <>
          <table
            className="mt-2 w-full text-left"
            aria-label={zh ? '修正前后状态' : 'Correction before and after'}
          >
            <thead>
              <tr>
                <th>{zh ? '项目' : 'Item'}</th>
                <th>{zh ? '修正前' : 'Before'}</th>
                <th>{zh ? '修正后' : 'After'}</th>
              </tr>
            </thead>
            <tbody>
              {changes.map(([label, previous, next]) => (
                <tr key={label}>
                  <th>{label}</th>
                  <td>{previous}</td>
                  <td>{next}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul
            className="mt-2 space-y-2"
            aria-label={zh ? '关联原流水' : 'Referenced ledger entries'}
          >
            {evidence.related_entries.map((row) => (
              <li key={`${row.role}-${row.id}`}>
                <span>
                  {row.role === 'original'
                    ? zh
                      ? '重复原流水'
                      : 'Original duplicate'
                    : zh
                      ? '保留流水'
                      : 'Retained entry'}{' '}
                  #{row.id}
                </span>
                <div>
                  {formatTimestamp(row.timestamp)} · {row.symbol} ·{' '}
                  {formatCurrency(row.amount)} · {formatQuantity(row.quantity)}
                </div>
                <div>
                  {zh ? '原记录类型' : 'Original entry type'}: {row.entry_type}{' '}
                  · {row.source}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      <details className="mt-2">
        <summary className="cursor-pointer">
          {zh ? '原始修正记录' : 'Raw correction record'}
        </summary>
        <div>
          {zh ? '修正引用' : 'Correction reference'}: {entry.source_ref || '--'}
        </div>
        <div>
          {zh ? '记录指纹' : 'Entry fingerprint'}:{' '}
          {entry.entry_fingerprint || '--'}
        </div>
        <p>{entry.note}</p>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap">
          {JSON.stringify(payload ?? null, null, 2)}
        </pre>
      </details>
    </details>
  );
}

function formatCorrectionTimestamp(
  value: string | null | undefined,
  locale: Locale,
) {
  if (!value) return '--';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '--';
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(date);
}
