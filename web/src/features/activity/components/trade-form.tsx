import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';

import { useCopy } from '../../../app/copy';
import { formatCurrency } from '../../../shared/format';

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
}: {
  onSubmit: (values: TradeFormValues) => Promise<void>;
  pending?: boolean;
  commissionSettings?: CommissionSettings;
}) {
  const copy = useCopy();
  const common = copy.common;
  const labels = copy.activity.forms.trade;
  const assetOptions = assetClassOptions(copy);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [feeWasEdited, setFeeWasEdited] = useState(false);
  const createDefaultValues = (): TradeFormValues => ({
    occurred_at: new Date().toISOString().slice(0, 16),
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

function FieldError({ message }: { message?: string }) {
  if (!message) {
    return null;
  }
  return <div className="app-error-text text-sm">{message}</div>;
}
