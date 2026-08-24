import { createContext, useContext } from 'react';

import type { SharedCopy } from './catalog';

export interface ApplicationCopy {
  states: SharedCopy['states'];
  common: SharedCopy['common'];
  mode: SharedCopy['mode'];
  explainability: SharedCopy['explainability'];
}

export type AppCopy = ApplicationCopy;

export const CopyContext = createContext<ApplicationCopy | null>(null);

export function useCopy(): ApplicationCopy {
  const copy = useContext(CopyContext);
  if (copy === null) {
    throw new Error('useCopy requires a localized copy provider');
  }
  return copy;
}
