export type BacktestMetrics = {
  initial_cash: number;
  final_equity: number;
  total_return: number;
  annual_return: number;
  sharpe: number;
  sortino: number;
  max_drawdown: number;
  calmar?: number | string;
  volatility?: number;
  win_rate: number;
  duration_days: number;
  total_commission?: number;
  total_slippage?: number;
  total_trades?: number;
  gross_turnover?: number;
};
