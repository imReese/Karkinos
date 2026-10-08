import { useBacktestPage } from './backtest-page-context';

export function ResearchUniverseEditor() {
  const {
    additionalAssets,
    assetClass,
    datasetPreparing,
    locale,
    runBacktest,
    setAdditionalAssets,
    setAssetClass,
    setSymbol,
    universeError,
  } = useBacktestPage();
  const zh = locale === 'zh';
  const disabled = datasetPreparing || runBacktest.isPending;
  return (
    <div className="min-w-0 space-y-3">
      {additionalAssets.map((asset, index) => (
        <div
          key={index}
          className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_120px_auto]"
        >
          <label className="grid min-w-0 gap-1 text-xs">
            {zh ? `篮子标的 ${index + 2}` : `Basket symbol ${index + 2}`}
            <input
              className="app-field min-h-11 min-w-0 px-3 py-2 tabular-nums"
              value={asset.symbol}
              disabled={disabled}
              placeholder="518880"
              onChange={(event) =>
                setAdditionalAssets((current) =>
                  current.map((row, position) =>
                    position === index
                      ? { ...row, symbol: event.target.value }
                      : row,
                  ),
                )
              }
            />
          </label>
          <label className="grid gap-1 text-xs">
            {zh ? `标的 ${index + 2} 类型` : `Asset ${index + 2} type`}
            <select
              className="app-field min-h-11 px-3 py-2"
              value={asset.asset_class}
              disabled={disabled}
              onChange={(event) =>
                setAdditionalAssets((current) =>
                  current.map((row, position) =>
                    position === index
                      ? { ...row, asset_class: event.target.value }
                      : row,
                  ),
                )
              }
            >
              <option value="stock">{zh ? '股票' : 'Stock'}</option>
              <option value="etf">ETF</option>
            </select>
          </label>
          <button
            type="button"
            className="app-button-secondary min-h-11 self-end px-3 py-2"
            disabled={disabled}
            aria-label={
              zh
                ? `移除篮子标的 ${index + 2}`
                : `Remove basket symbol ${index + 2}`
            }
            onClick={() =>
              setAdditionalAssets((current) =>
                current.filter((_, position) => position !== index),
              )
            }
          >
            {zh ? '移除' : 'Remove'}
          </button>
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="app-button-secondary min-h-11 px-3 py-2 text-xs"
          disabled={
            disabled ||
            additionalAssets.length >= 31 ||
            !['stock', 'etf'].includes(assetClass)
          }
          onClick={() =>
            setAdditionalAssets((current) => [
              ...current,
              { symbol: '', asset_class: assetClass },
            ])
          }
        >
          {zh ? '添加股票 / ETF' : 'Add stock / ETF'}
        </button>
        <button
          type="button"
          className="app-button-secondary min-h-11 px-3 py-2 text-xs"
          disabled={disabled}
          onClick={() => {
            setSymbol('510300');
            setAssetClass('etf');
            setAdditionalAssets([
              { symbol: '511010', asset_class: 'etf' },
              { symbol: '518880', asset_class: 'etf' },
            ]);
          }}
        >
          {zh ? '填入 ETF 示例篮子' : 'Use ETF example basket'}
        </button>
      </div>
      <p className="app-muted text-xs leading-5">
        {zh
          ? '示例为 510300、518880 与 511010，不是投资推荐。资产篮子最多 32 个标的；轮动策略的现金替代标的也须包含在数据中。准备数据、单次回测、扫描与对比共用完整篮子和日期。'
          : 'The 510300, 518880 and 511010 basket is an example, not an investment recommendation. Use up to 32 instruments and include the rotation strategy’s cash proxy. Preparation, backtest, sweep and comparison use the same complete basket and dates.'}
      </p>
      {universeError ? (
        <p role="alert" className="text-xs text-[var(--app-danger)]">
          {universeError}
        </p>
      ) : null}
    </div>
  );
}
