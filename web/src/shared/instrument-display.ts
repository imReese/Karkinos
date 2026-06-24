export type InstrumentDisplayRecord = {
  symbol?: string | null;
  display_name?: string | null;
  name?: string | null;
};

export function formatInstrumentDisplayLabel(
  instrument: InstrumentDisplayRecord | null | undefined,
) {
  const symbol = instrument?.symbol?.trim() ?? '';
  const displayName =
    instrument?.display_name?.trim() || instrument?.name?.trim() || '';

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
