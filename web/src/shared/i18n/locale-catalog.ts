import type { Locale } from '../locale';

export type LocalizedCatalog<T> = Readonly<Record<Locale, T>>;

export function resolveLocalizedCatalog<T>(
  catalog: LocalizedCatalog<T>,
  locale: Locale,
): T {
  return catalog[locale];
}
