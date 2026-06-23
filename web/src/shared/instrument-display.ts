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
