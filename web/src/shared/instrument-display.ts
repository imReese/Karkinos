export type InstrumentDisplayRecord = {
  symbol?: string | null;
  display_name?: string | null;
  name?: string | null;
};

const COMMON_A_SHARE_NAMES: Record<string, string> = {
  '601985': '中国核电',
  '600050': '中国联通',
  '600886': '国投电力',
  '000725': '京东方A',
  '600519': '贵州茅台',
  '601318': '中国平安',
  '000001': '平安银行',
  '000002': '万科A',
  '000858': '五粮液',
  '300750': '宁德时代',
  '600036': '招商银行',
  '510300': '沪深300ETF',
  '510500': '中证500ETF',
  '159915': '创业板ETF',
  '588000': '科创50ETF',
};

export function formatInstrumentDisplayLabel(
  instrument: InstrumentDisplayRecord | null | undefined,
) {
  const symbol = instrument?.symbol?.trim() ?? '';
  const displayName =
    instrument?.display_name?.trim() ||
    instrument?.name?.trim() ||
    (symbol
      ? (COMMON_A_SHARE_NAMES[symbol.toLowerCase()] ??
        COMMON_A_SHARE_NAMES[symbol])
      : '') ||
    '';

  if (!displayName) {
    return symbol || '--';
  }
  if (!symbol || displayName === symbol) {
    return displayName;
  }
  return `${displayName} ${symbol}`;
}

export function formatInstrumentDisplayLabelsBySymbol(
  symbols: string[],
  instruments: InstrumentDisplayRecord[],
) {
  const instrumentBySymbol = new Map(
    instruments
      .filter((instrument) => instrument.symbol?.trim())
      .flatMap((instrument) => {
        const symbol = instrument.symbol?.trim() ?? '';
        return [
          [symbol, instrument],
          [symbol.toLowerCase(), instrument],
        ] as const;
      }),
  );

  return symbols
    .map((symbol) => {
      const normalizedSymbol = symbol.trim();
      const instrument =
        instrumentBySymbol.get(normalizedSymbol) ??
        instrumentBySymbol.get(normalizedSymbol.toLowerCase());
      return instrument
        ? formatInstrumentDisplayLabel(instrument)
        : normalizedSymbol;
    })
    .join(', ');
}

export function formatInstrumentDisplayLabelFromNameMap(
  symbol: string,
  instrumentNames?: Map<string, string>,
) {
  const normalizedSymbol = symbol.trim();
  const name = normalizedSymbol
    ? instrumentNames?.get(normalizedSymbol.toLowerCase())
    : null;
  if (!name || name === symbol) {
    return symbol;
  }
  return `${name} ${symbol}`;
}
