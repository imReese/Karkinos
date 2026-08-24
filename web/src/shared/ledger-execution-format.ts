import { formatCurrency, formatQuantity } from './format';
import type { Locale } from './locale';
import type {
  LedgerExecutionDetailLabels,
  LedgerExecutionDetailLine,
  PublicLedgerEntry,
} from './ledger-format-contracts';
import {
  finiteBreakdownNumber,
  finiteNumber,
  isCashLedgerEntry,
  isFundLedgerEntry,
  sumBreakdownNumbers,
} from './ledger-format-values';

export function formatLedgerExecutionDetailLines(
  entry: PublicLedgerEntry,
  labels: LedgerExecutionDetailLabels,
  _locale: Locale,
): LedgerExecutionDetailLine[] {
  const hasStructuredCosts =
    finiteNumber(entry.gross_amount) !== null ||
    finiteNumber(entry.net_cash_impact) !== null ||
    Boolean(entry.fee_breakdown);
  const breakdown = entry.fee_breakdown ?? null;
  const isCashEntry = isCashLedgerEntry(entry);
  const lines: LedgerExecutionDetailLine[] = [];

  if (isCashEntry) {
    const cashAmount =
      finiteNumber(entry.net_cash_impact) ??
      finiteNumber(entry.gross_amount) ??
      finiteNumber(entry.amount);
    addLine(lines, labels.amount, formatCurrency(cashAmount));

    const cashFee = breakdown
      ? sumBreakdownNumbers(
          breakdown,
          'commission',
          'stamp_tax',
          'tax',
          'transfer_fee',
          'other_fees',
        )
      : finiteNumber(entry.commission);
    if (cashFee !== null && cashFee !== 0) {
      addLine(lines, labels.fee, formatCurrency(cashFee));
    }
    return lines;
  }

  addLine(
    lines,
    hasStructuredCosts ? labels.grossAmount : labels.amount,
    formatCurrency(finiteNumber(entry.gross_amount ?? entry.amount)),
  );
  if (hasStructuredCosts) {
    addLine(
      lines,
      labels.netCashImpact,
      formatCurrency(finiteNumber(entry.net_cash_impact)),
    );
  }
  addLine(lines, labels.quantity, formatQuantity(finiteNumber(entry.quantity)));
  addLine(lines, labels.price, formatCurrency(finiteNumber(entry.price)));

  if (breakdown) {
    if (isFundLedgerEntry(entry)) {
      const fundFee = sumBreakdownNumbers(
        breakdown,
        'commission',
        'subscription_fee',
        'redemption_fee',
      );
      if (fundFee !== null && fundFee !== 0) {
        addLine(lines, labels.fee, formatCurrency(fundFee));
      }
      const otherFees = finiteBreakdownNumber(breakdown, 'other_fees');
      if (otherFees !== null && otherFees !== 0) {
        addLine(lines, labels.otherFees, formatCurrency(otherFees));
      }
      return lines;
    }
    addLine(
      lines,
      labels.commission,
      formatCurrency(finiteBreakdownNumber(breakdown, 'commission')),
    );
    addLine(
      lines,
      labels.stampTax,
      formatCurrency(finiteBreakdownNumber(breakdown, 'stamp_tax', 'tax')),
    );
    addLine(
      lines,
      labels.transferFee,
      formatCurrency(finiteBreakdownNumber(breakdown, 'transfer_fee')),
    );
    const otherFees = finiteBreakdownNumber(breakdown, 'other_fees');
    if (otherFees !== null && otherFees !== 0) {
      addLine(lines, labels.otherFees, formatCurrency(otherFees));
    }
  } else {
    const fee = finiteNumber(entry.commission);
    if (!isFundLedgerEntry(entry) || (fee !== null && fee !== 0)) {
      addLine(lines, labels.fee, formatCurrency(fee));
    }
  }

  return lines;
}

function addLine(
  lines: LedgerExecutionDetailLine[],
  label: string,
  value: string | null,
) {
  if (value === null || value === '--') {
    return;
  }
  lines.push({ label, value });
}
