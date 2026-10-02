import { cashDividendCopy } from '../copy-cash-dividends';
import { useBacktestPage } from './backtest-page-context';

export function CashDividendModeControl() {
  const {
    locale,
    selectedDataset,
    corporateActionMode,
    setCorporateActionMode,
    datasetPreparing,
    runBacktest,
  } = useBacktestPage();
  const labels = cashDividendCopy[locale];
  const supported = Boolean(
    selectedDataset?.corporate_action_evidence &&
    selectedDataset.instruments.length > 0 &&
    selectedDataset.instruments.every(
      (item) => item.instrument_type === 'stock',
    ),
  );
  return (
    <div className="grid min-w-0 gap-2">
      <label className="grid gap-2 text-sm font-medium">
        {labels.mode}
        <select
          className="app-field min-h-11 w-full min-w-0 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm"
          value={corporateActionMode}
          disabled={!supported || datasetPreparing || runBacktest.isPending}
          onChange={(event) =>
            setCorporateActionMode(
              event.target.value === 'cash_dividends_gross'
                ? 'cash_dividends_gross'
                : event.target.value === 'reported_distributions_gross'
                  ? 'reported_distributions_gross'
                  : 'price_only',
            )
          }
        >
          <option value="price_only">{labels.priceOnly}</option>
          <option value="cash_dividends_gross">{labels.gross}</option>
          <option value="reported_distributions_gross">
            {labels.reported}
          </option>
        </select>
      </label>
      <p className="app-muted text-xs leading-5">
        {supported
          ? corporateActionMode === 'reported_distributions_gross'
            ? labels.reportedDetail
            : labels.modeDetail
          : labels.requiresEvidence}
      </p>
    </div>
  );
}
