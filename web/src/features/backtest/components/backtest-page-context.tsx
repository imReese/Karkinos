import { createContext, useContext, type ReactNode } from 'react';

import { useBacktestPageController } from './use-backtest-page-controller';

type BacktestPageController = ReturnType<typeof useBacktestPageController>;

const BacktestPageContext = createContext<BacktestPageController | null>(null);

export function BacktestPageProvider({ children }: { children: ReactNode }) {
  const controller = useBacktestPageController();
  return (
    <BacktestPageContext.Provider value={controller}>
      {children}
    </BacktestPageContext.Provider>
  );
}

export function useBacktestPage() {
  const controller = useContext(BacktestPageContext);
  if (!controller) {
    throw new Error('useBacktestPage must be used within BacktestPageProvider');
  }
  return controller;
}
