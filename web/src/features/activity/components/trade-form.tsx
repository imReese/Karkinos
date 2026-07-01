import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';

import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
import { formatCurrency } from '../../../shared/format';
import {
  formatLedgerCostBasisMethodLabel,
  formatLedgerFeeRuleLabel,
} from '../../../shared/ledger-format';
import type { TradePreview } from '../api';
import { toDatetimeLocalInputValue } from '../datetime-local';

export type TradeFormValues = {
  occurred_at: string;
  symbol: string;
  asset_class: string;
  direction: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
  fee: number;
  fee_is_manual: boolean;
  note: string;
};

export type CommissionSettings = {
  stock_rate: number;
  stock_min_commission: number;
};

function calculateCommission({
  assetClass,
  quantity,
  price,
  settings,
}: {
  assetClass: string;
  quantity: number | null;
  price: number | null;
  settings?: CommissionSettings;
}) {
  if (!settings || !['stock', 'etf'].includes(assetClass.toLowerCase())) {
    return null;
  }
  if (
    typeof quantity !== 'number' ||
    !Number.isFinite(quantity) ||
    quantity <= 0 ||
    typeof price !== 'number' ||
    !Number.isFinite(price) ||
    price <= 0
  ) {
    return null;
  }
  const calculated = Math.max(
    quantity * price * settings.stock_rate,
    settings.stock_min_commission,
  );
  return Number(calculated.toFixed(2));
}

function assetClassOptions(copy: ReturnType<typeof useCopy>) {
  return [
    { value: 'stock', label: copy.common.assetClassStock },
    { value: 'etf', label: copy.common.assetClassEtf },
    { value: 'fund', label: copy.common.assetClassFund },
    { value: 'gold', label: copy.common.assetClassGold },
    { value: 'bond', label: copy.common.assetClassBond },
  ];
}

export function TradeForm({
  onSubmit,
  pending = false,
  commissionSettings,
  tradePreview = null,
  previewLoading = false,
  previewError = false,
  onPreviewChange,
}: {
  onSubmit: (values: TradeFormValues) => Promise<void>;
  pending?: boolean;
  commissionSettings?: CommissionSettings;
  tradePreview?: TradePreview | null;
  previewLoading?: boolean;
  previewError?: boolean;
  onPreviewChange?: (values: TradeFormValues) => void;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const common = copy.common;
  const labels = copy.activity.forms.trade;
  const assetOptions = assetClassOptions(copy);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [feeWasEdited, setFeeWasEdited] = useState(false);
  const createDefaultValues = (): TradeFormValues => ({
    occurred_at: toDatetimeLocalInputValue(),
    asset_class: 'stock',
    direction: 'buy',
    quantity: null,
    unit_price: null,
    amount: null,
    fee: 0,
    fee_is_manual: false,
    note: '',
    symbol: '',
  });

  const {
    register,
    handleSubmit,
    watch,
    reset,
    setValue,
    formState: { errors },
  } = useForm<TradeFormValues>({
    defaultValues: createDefaultValues(),
  });
  const assetClass = watch('asset_class');
  const direction = watch('direction');
  const quantity = watch('quantity');
  const price = watch('unit_price');
  const occurredAt = watch('occurred_at');
  const symbol = watch('symbol');
  const amount = watch('amount');
  const fee = watch('fee');
  const feeIsManual = watch('fee_is_manual');
  const note = watch('note');
  const isFundBuy =
    assetClass.trim().toLowerCase() === 'fund' && direction === 'buy';
  const calculatedCommission = calculateCommission({
    assetClass,
    quantity,
    price,
    settings: commissionSettings,
  });

  useEffect(() => {
    if (feeWasEdited || calculatedCommission === null) {
      return;
    }
    setValue('fee', calculatedCommission);
    setValue('fee_is_manual', false);
  }, [calculatedCommission, feeWasEdited, setValue]);

  useEffect(() => {
    onPreviewChange?.({
      occurred_at: occurredAt,
      symbol,
      asset_class: assetClass,
      direction,
      quantity,
      unit_price: price,
      amount,
      fee,
      fee_is_manual: feeIsManual,
      note,
    });
  }, [
    amount,
    assetClass,
    direction,
    fee,
    feeIsManual,
    note,
    occurredAt,
    onPreviewChange,
    price,
    quantity,
    symbol,
  ]);

  return (
    <form
      onSubmit={handleSubmit(async (values) => {
        setSubmitError(null);
        try {
          await onSubmit(values);
          reset(createDefaultValues());
          setFeeWasEdited(false);
        } catch (error) {
          setSubmitError(
            error instanceof Error ? error.message : labels.genericSubmitError,
          );
        }
      })}
      className="app-panel space-y-3 rounded-2xl p-5"
    >
      <div className="app-kicker text-xs uppercase tracking-[0.18em]">
        {labels.title}
      </div>
      <input
        aria-label={labels.occurredAtLabel}
        type="datetime-local"
        className="app-field w-full rounded-2xl px-4 py-3 text-sm"
        {...register('occurred_at', { required: common.required })}
      />
      {errors.occurred_at ? (
        <FieldError message={errors.occurred_at.message} />
      ) : null}
      <input
        aria-label={labels.symbolLabel}
        placeholder={labels.symbolPlaceholder}
        className="app-field w-full rounded-2xl px-4 py-3 text-sm"
        {...register('symbol', { required: common.required })}
      />
      {errors.symbol ? <FieldError message={errors.symbol.message} /> : null}
      <div className="grid gap-3 md:grid-cols-2">
        <select
          aria-label={labels.directionLabel}
          className="app-field rounded-2xl px-4 py-3 text-sm"
          {...register('direction', { required: common.required })}
        >
          <option value="buy">{labels.buy}</option>
          <option value="sell">{labels.sell}</option>
        </select>
        <select
          aria-label={labels.assetClassLabel}
          className="app-field rounded-2xl px-4 py-3 text-sm"
          {...register('asset_class', { required: common.required })}
        >
          {assetOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      {errors.asset_class ? (
        <FieldError message={errors.asset_class.message} />
      ) : null}
      {isFundBuy ? (
        <>
          <input
            aria-label={labels.subscriptionAmountLabel}
            type="number"
            step="any"
            placeholder={labels.amountPlaceholder}
            className="app-field w-full rounded-2xl px-4 py-3 text-sm"
            {...register('amount', {
              valueAsNumber: true,
              validate: (value) =>
                typeof value === 'number' && value > 0
                  ? true
                  : labels.amountRequired,
            })}
          />
          {errors.amount ? (
            <FieldError message={errors.amount.message} />
          ) : null}
          <div className="app-muted text-xs">{labels.fundAmountHelp}</div>
        </>
      ) : null}
      <div className="grid gap-3 md:grid-cols-3">
        <input
          aria-label={labels.quantityLabel}
          type="number"
          step="any"
          placeholder={labels.quantityPlaceholder}
          className="app-field rounded-2xl px-4 py-3 text-sm"
          {...register('quantity', {
            valueAsNumber: true,
            validate: (value) =>
              isFundBuy ||
              (typeof value === 'number' && value > 0) ||
              common.mustBePositive,
          })}
        />
        <input
          aria-label={labels.priceLabel}
          type="number"
          step="any"
          placeholder={labels.pricePlaceholder}
          className="app-field rounded-2xl px-4 py-3 text-sm"
          {...register('unit_price', {
            valueAsNumber: true,
            validate: (value) =>
              isFundBuy ||
              (typeof value === 'number' && value > 0) ||
              common.mustBePositive,
          })}
        />
        <input
          aria-label={labels.feeLabel}
          type="number"
          step="any"
          className="app-field rounded-2xl px-4 py-3 text-sm"
          {...register('fee', {
            valueAsNumber: true,
            onChange: () => {
              setFeeWasEdited(true);
              setValue('fee_is_manual', true);
            },
          })}
        />
        <input type="hidden" {...register('fee_is_manual')} />
      </div>
      {commissionSettings ? (
        <div className="app-muted text-xs leading-5">
          {labels.commissionHelp(
            commissionSettings.stock_rate * 10000,
            formatCurrency(commissionSettings.stock_min_commission),
          )}
        </div>
      ) : null}
      {previewLoading ? (
        <div className="app-muted rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] px-4 py-3 text-xs leading-5">
          {labels.previewLoading}
        </div>
      ) : null}
      {previewError ? (
        <div className="app-error-text rounded-2xl border border-[var(--app-danger-border)] px-4 py-3 text-xs leading-5">
          {labels.previewUnavailable}
        </div>
      ) : null}
      {tradePreview ? (
        <TradePreviewPanel
          preview={tradePreview}
          labels={labels}
          locale={locale}
        />
      ) : null}
      {errors.quantity ? (
        <FieldError message={errors.quantity.message} />
      ) : null}
      {errors.unit_price ? (
        <FieldError message={errors.unit_price.message} />
      ) : null}
      <input
        aria-label={labels.noteLabel}
        placeholder={labels.notePlaceholder}
        className="app-field w-full rounded-2xl px-4 py-3 text-sm"
        {...register('note')}
      />
      {submitError ? <FieldError message={submitError} /> : null}
      <button
        type="submit"
        disabled={pending}
        className="app-button-primary rounded-2xl px-5 py-3 text-sm font-semibold disabled:opacity-50"
      >
        {pending ? labels.saving : labels.submit}
      </button>
    </form>
  );
}

function readFeeBreakdown(preview: TradePreview, key: string) {
  const value = preview.fee_breakdown[key];
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function TradePreviewPanel({
  preview,
  labels,
  locale,
}: {
  preview: TradePreview;
  labels: ReturnType<typeof useCopy>['activity']['forms']['trade'];
  locale: ReturnType<typeof usePreferences>['locale'];
}) {
  const stampTax = readFeeBreakdown(preview, 'stamp_tax') ?? 0;
  const transferFee = readFeeBreakdown(preview, 'transfer_fee') ?? 0;
  const otherFees = readFeeBreakdown(preview, 'other_fees') ?? 0;

  return (
    <section className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] p-4">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="app-kicker text-xs uppercase tracking-[0.18em]">
          {labels.previewTitle}
        </div>
        <div className="app-chip min-w-0 truncate">
          {formatLedgerFeeRuleLabel(preview.fee_rule_id, locale)}
        </div>
      </div>
      <div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2">
        <PreviewMetric
          label={labels.previewGrossAmount}
          value={formatCurrency(preview.gross_amount)}
        />
        <PreviewMetric
          label={labels.previewNetCashImpact}
          value={formatCurrency(preview.net_cash_impact)}
        />
        <PreviewMetric
          label={labels.previewCommission}
          value={formatCurrency(preview.commission)}
        />
        <PreviewMetric
          label={labels.previewStampTax}
          value={formatCurrency(stampTax)}
        />
        <PreviewMetric
          label={labels.previewTransferFee}
          value={formatCurrency(transferFee)}
        />
        {otherFees !== 0 ? (
          <PreviewMetric
            label={labels.previewOtherFees}
            value={formatCurrency(otherFees)}
          />
        ) : null}
        <PreviewMetric
          label={labels.previewTotalFee}
          value={formatCurrency(preview.total_fee)}
        />
        <PreviewMetric
          label={labels.previewFeeRule}
          value={`${formatLedgerFeeRuleLabel(preview.fee_rule_id, locale)} · ${
            preview.fee_rule_version
          }`}
        />
        <PreviewMetric
          label={labels.previewCostBasisMethod}
          value={formatLedgerCostBasisMethodLabel(
            preview.cost_basis_method,
            locale,
          )}
        />
      </div>
    </section>
  );
}

function PreviewMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2">
      <div className="app-muted text-xs">{label}</div>
      <div className="mt-1 min-w-0 break-words text-sm font-semibold">
        {value}
      </div>
    </div>
  );
}

function FieldError({ message }: { message?: string }) {
  if (!message) {
    return null;
  }
  return <div className="app-error-text text-sm">{message}</div>;
}
