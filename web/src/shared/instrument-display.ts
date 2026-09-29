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
  '603659': '璞泰来',
  '600869': '远东股份',
  '600000': '浦发银行',
  '601166': '兴业银行',
  '601398': '工商银行',
  '601288': '农业银行',
  '601939': '建设银行',
  '601988': '中国银行',
  '000333': '美的集团',
  '000651': '格力电器',
  '002594': '比亚迪',
  '510300': '沪深300ETF',
  '510500': '中证500ETF',
  '159915': '创业板ETF',
  '588000': '科创50ETF',
  '518880': '黄金ETF',
};

const dynamicInstrumentNames = new Map<string, string>();

export function registerInstrumentDisplayNames(
  entries:
    | Array<InstrumentDisplayRecord | null | undefined>
    | Record<string, string | null | undefined>
    | null
    | undefined,
) {
  if (!entries) return;
  if (Array.isArray(entries)) {
    for (const item of entries) {
      const sym = item?.symbol?.trim();
      const name = item?.display_name?.trim() || item?.name?.trim();
      if (sym && name) {
        dynamicInstrumentNames.set(sym, name);
        dynamicInstrumentNames.set(sym.toLowerCase(), name);
        dynamicInstrumentNames.set(sym.toUpperCase(), name);
      }
    }
  } else if (typeof entries === 'object') {
    for (const [sym, rawName] of Object.entries(entries)) {
      const trimmedSym = sym?.trim();
      const trimmedName = rawName?.trim();
      if (trimmedSym && trimmedName) {
        dynamicInstrumentNames.set(trimmedSym, trimmedName);
        dynamicInstrumentNames.set(trimmedSym.toLowerCase(), trimmedName);
        dynamicInstrumentNames.set(trimmedSym.toUpperCase(), trimmedName);
      }
    }
  }
}

export function formatInstrumentDisplayLabel(
  instrument: InstrumentDisplayRecord | null | undefined,
) {
  const symbol = instrument?.symbol?.trim() ?? '';
  const displayName =
    instrument?.display_name?.trim() ||
    instrument?.name?.trim() ||
    (symbol
      ? (dynamicInstrumentNames.get(symbol) ??
        dynamicInstrumentNames.get(symbol.toLowerCase()) ??
        dynamicInstrumentNames.get(symbol.toUpperCase()) ??
        COMMON_A_SHARE_NAMES[symbol.toLowerCase()] ??
        COMMON_A_SHARE_NAMES[symbol.toUpperCase()] ??
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
