import type { Locale } from './locale';

type LabelMap = Record<string, string>;

export const CODE_LABELS: Record<Locale, LabelMap> = {
  en: {
    canonical_broker_evidence: 'Canonical broker evidence',
    current_cash_snapshot: 'Current cash snapshot',
    current_position_snapshot: 'Current position snapshot',
    itemized_settlement_fees_and_taxes: 'Itemized settlement fees and taxes',
    position_cost_basis: 'Position cost basis',
    freshness_and_ledger_coverage: 'Freshness and ledger coverage',
    reconciliation_gate: 'Reconciliation gate',
    known_incomplete_source_reviews: 'Known incomplete source reviews',
    reviewed_account_and_period_scope: 'Reviewed account and period scope',
    account_truth_account_scope_unbound:
      'Broker evidence is not bound to a reviewed account scope',
    account_truth_coverage_window_undeclared:
      'No reviewed coverage period is recorded for this broker evidence',
    account_truth_asset_scope_completeness_unverified:
      'Observed assets do not prove complete account coverage',
    account_truth_evidence_scope_missing:
      'No persisted evidence-scope projection is available',
    account_truth_evidence_scope_import_mismatch:
      'Evidence scope does not match the selected Account Truth import',
    account_truth_evidence_scope_event_count_mismatch:
      'Persisted event count does not match the selected import',
    account_truth_observed_event_time_invalid:
      'A persisted broker event has an invalid time',
    account_truth_observed_scope_code_invalid:
      'A persisted broker event has an invalid scope code',
    account_truth_observed_events_missing:
      'No persisted broker events are available for scope review',
    account_truth_evidence_scope_review_import_mismatch:
      'The scope review targets a different Account Truth import',
    account_truth_evidence_scope_review_source_drift:
      'The broker source changed after scope review',
    account_truth_evidence_scope_review_observed_drift:
      'Observed broker evidence changed after scope review',
    account_truth_evidence_scope_review_revoked:
      'The reviewed evidence scope was revoked',
    account_truth_evidence_scope_review_window_incomplete:
      'The reviewed period does not contain every observed broker event',
    account_truth_evidence_scope_review_assets_incomplete:
      'The reviewed asset scope omits an observed asset class',
    account_truth_evidence_scope_review_attestation_missing:
      'Full-account scope attestation is missing',
    bind_account_truth_evidence_to_reviewed_account_scope:
      'Bind the evidence to a reviewed account scope',
    record_reviewed_account_truth_coverage_window:
      'Record the reviewed coverage period for this evidence',
    review_account_truth_asset_scope_completeness:
      'Review whether every account asset class is covered',
    record_reviewed_account_truth_evidence_scope:
      'Record a reviewed account and period scope',
    account_truth_gate_pass: 'Account truth gate must pass',
    account_truth_score_unavailable:
      'Account truth score is unavailable because no broker evidence has been staged',
    account_truth_evidence_predates_latest_ledger:
      'Broker evidence predates the latest local ledger fact',
    reimport_broker_statement_after_latest_ledger_fact:
      'Import a broker statement captured after the latest local ledger fact',
    after_cost_report: 'After-cost report',
    account_truth: 'Account truth',
    cash: 'Cash',
    cash_missing: 'Cash evidence is missing',
    commission: 'Commission',
    cost_basis: 'Cost basis',
    cost_basis_method: 'Cost-basis method',
    cost_basis_missing: 'Cost-basis evidence is missing',
    data_refresh: 'Data refresh',
    evidence_linked_pnl_pending: 'Evidence linked, P/L pending',
    fee: 'Fee',
    estimated_from_linked_fills: 'Estimated from linked fills',
    evidence_bound_from_posted_fills:
      'Bound to posted fills and valuation evidence',
    ledger_posting_pending: 'Ledger posting pending',
    ledger_evidence_drift: 'Fill and ledger evidence do not match',
    valuation_snapshot_missing: 'Persisted valuation snapshot is missing',
    valuation_snapshot_invalid: 'Persisted valuation snapshot is invalid',
    valuation_identity_drift: 'Valuation snapshot identity has drifted',
    inventory_lineage_incomplete: 'Strategy inventory lineage is incomplete',
    fee_missing: 'Fee evidence is missing',
    gross_amount: 'Gross amount',
    holding_evidence_linked_review_required:
      'Holding evidence linked; review required',
    holding_orders_linked_no_fills: 'Holding orders linked; fills pending',
    holding_signal_chain_pending: 'Holding signals pending order/fill evidence',
    import_and_reconcile_broker_evidence:
      'Import broker evidence and run reconciliation',
    provide_cash_snapshot: 'Provide a current cash snapshot',
    provide_position_snapshot: 'Provide a current position snapshot',
    provide_itemized_settlement_or_cash_flow:
      'Provide an itemized settlement or cash-flow statement',
    provide_position_cost_basis_evidence:
      'Provide position cost-basis evidence',
    refresh_broker_evidence_covering_latest_ledger:
      'Refresh broker evidence covering the latest ledger fact',
    resolve_account_truth_blockers: 'Resolve Account Truth blockers',
    provide_citic_account_truth_evidence_or_reject_source:
      'Provide the missing CITIC evidence or reject the source',
    review_citic_source_query_windows:
      'Review each exact CITIC source query window',
    review_citic_source_intake_scan_limit:
      'Review the CITIC source scan limit and restore a complete count',
    repair_citic_source_intake_metadata_store:
      'Repair the CITIC source-review metadata store',
    repair_citic_source_query_window_review_store:
      'Repair the CITIC query-window review store',
    reviewed_query_window_for_source:
      'Reviewed query window for this exact source',
    reviewed_query_window_for_each_source:
      'Reviewed query window for every exact source',
    complete_citic_source_intake_scan: 'Complete CITIC source-review scan',
    contiguous_non_overlapping_reviewed_query_windows:
      'Contiguous, non-overlapping reviewed query windows',
    citic_source_follow_up_required:
      'Known CITIC sources still require evidence review',
    citic_source_intake_scan_truncated:
      'CITIC source-review scan reached its safety limit',
    citic_query_window_batch_calendar_gap:
      'Reviewed query windows contain a calendar gap',
    citic_query_window_batch_calendar_overlap:
      'Reviewed query windows contain overlapping days',
    citic_query_window_batch_sources_unreviewed:
      'Some CITIC sources still lack reviewed query windows',
    citic_source_intake_schema_incomplete:
      'CITIC source-review metadata schema is incomplete',
    citic_source_intake_store_unreadable:
      'CITIC source-review metadata store is unreadable',
    citic_source_query_window_review_schema_incomplete:
      'CITIC query-window review schema is incomplete',
    citic_source_query_window_review_store_unreadable:
      'CITIC query-window review store is unreadable',
    citic_history_xls_non_financial_activity_ignored:
      'Reviewed non-financial designated-trading activity — no broker event created',
    citic_history_xls_invalid_non_financial_activity:
      'Designated-trading activity does not match the reviewed non-financial shape',
    review_non_financial_activity:
      'Review recognized non-financial designated-trading activity',
    versioned_readonly_connector_snapshot:
      'Versioned read-only connector snapshot',
    reviewed_account_alias_binding: 'Reviewed account-alias binding',
    provider_source_captured_at: 'Provider source capture time',
    connector_deployment_identity: 'Connector deployment identity',
    connector_health_evidence: 'Connector health evidence',
    current_order_snapshot: 'Current order snapshot',
    itemized_fill_fees_and_taxes: 'Itemized fill fees and taxes',
    link_strategy_signals_orders_fills_and_contribution:
      'Link strategy signals, reviews, orders, fills, and contribution evidence',
    manual_confirm_candidate_actions: 'Manually confirm candidate actions',
    manual_confirmation: 'Manual confirmation',
    market_data_missing: 'Market data is missing',
    market_data_not_fully_live: 'Market data needs confirmation',
    no_intraday_stock_or_etf_action_tasks:
      'No intraday stock or ETF action candidates',
    no_linked_fills: 'No linked fills',
    net_cash_impact: 'Net cash impact',
    other_fees: 'Other fees',
    out_of_sample_validation: 'Out-of-sample validation',
    paper_shadow_divergence_review: 'Simulation-review divergence review',
    paper_shadow_evidence: 'Simulation-review evidence',
    paper_shadow_review: 'Simulation review',
    paper_shadow_evidence_required_before_manual_confirmation:
      'Simulation-review evidence required before manual confirmation',
    broker_cost_basis_method: 'Broker cost-basis method',
    karkinos_cost_basis_method: 'Karkinos cost-basis method',
    broker_remaining_cost: 'Broker remaining-position cost',
    moving_average_buy_cost: 'Moving average buy cost',
    comparison_unit: 'Comparison unit',
    per_share_cost_basis: 'Per-share cost basis',
    comparison_precision: 'Comparison precision',
    decimal_string_no_rounding: 'Original decimal value',
    precision_limitation: 'Precision limitation',
    broker_display_precision_fee_allocation_tax_timing_transfer_fee_rounding:
      'Broker display precision, fee allocation, tax timing, and transfer-fee rounding may differ',
    position: 'Position',
    position_missing: 'Position evidence is missing',
    preview_import_and_reconcile_broker_evidence:
      'Preview broker evidence import and run reconciliation',
    quote_older_than_expected_session:
      'Quote is older than the expected trading session',
    refresh_market_data: 'Refresh market data',
    refresh_or_confirm_market_data: 'Refresh or confirm market data',
    refresh_quotes_or_check_source: 'Refresh quotes or check data source',
    resolve_account_truth_before_rebalance:
      'Resolve account truth before rebalancing',
    resolve_upstream_workflow_blockers: 'Resolve upstream workflow blockers',
    review_position_difference: 'Review position difference',
    review_cash_difference: 'Review cash difference',
    review_cost_basis_difference: 'Review cost-basis difference',
    review_fee_difference: 'Review fee difference',
    review_net_cash_impact_difference: 'Review net cash impact difference',
    review_tax_difference: 'Review tax difference',
    review_trade_gross_amount_difference:
      'Review trade gross amount difference',
    review_transfer_fee_difference: 'Review transfer-fee difference',
    review_paper_shadow_evidence: 'Review simulation evidence',
    review_blocked_risk_gate: 'Review blocked risk gate reason',
    review_risk_blockers: 'Review risk blockers',
    risk_gate_blocked: 'Risk gate is blocking action',
    risk_gate_not_checked: 'Risk gate has not checked every action',
    risk_review: 'Risk review',
    'order.fill.recorded': 'Fill recorded',
    'order.recorded': 'Order recorded',
    'order.shadow_divergence_reviewed': 'Simulation divergence review recorded',
    'order.status_changed': 'Order status changed',
    'order.submitted': 'Order submitted',
    'signal.review.recorded': 'Signal review recorded',
    'task.action.created': 'Action task created',
    'task.action.status_changed': 'Action task status changed',
    'task_run.completed': 'Task run completed',
    'task_run.started': 'Task run started',
    'risk.signal.recorded': 'Risk signal recorded',
    run_pre_trade_risk_gate: 'Run pre-trade risk gate',
    run_first_sync: 'Configure a data source or run the first sync',
    risk_block_evidence: 'Risk block evidence',
    stamp_tax: 'Stamp tax',
    strategy_evidence: 'Strategy evidence',
    strategy_attribution_evidence: 'Strategy attribution evidence',
    strategy_attribution_not_ready:
      'Strategy attribution evidence is not ready',
    upstream_workflow_blockers: 'Upstream workflow blockers remain unresolved',
    tax: 'Tax',
    trade_gross_amount: 'Trade gross amount',
    transfer_fee: 'Transfer fee',
    unresolved_position_difference: 'Unresolved position difference',
    decision_generated_outside_reviewed_window:
      'Decision was generated outside the reviewed window',
    plan_generated_outside_reviewed_window:
      'Trading plan was generated outside the reviewed window',
    account_truth_promotion_status_not_clear:
      'Account Truth is not cleared for strategy promotion',
    account_truth_gate_not_pass: 'Account Truth gate has not passed',
    account_truth_not_fresh: 'Account Truth snapshot is stale',
    account_truth_not_bound_to_plan_date:
      'Account Truth is not bound to the run date',
    account_truth_age_exceeds_reviewed_limit:
      'Account Truth exceeds the reviewed freshness limit',
    account_truth_too_old_for_decision:
      'Account Truth was too old when the Decision was generated',
    market_quote_timestamp_missing_or_invalid:
      'Persisted market quote time is missing or invalid',
    daily_candidate_strategy_candidate_missing:
      'No promoted strategy candidate is available',
    reviewed_fee_schedule_review_missing:
      'Reviewed fee schedule approval is missing',
    reviewed_fee_schedule_not_active: 'Reviewed fee schedule is not active',
    reviewed_fee_schedule_review_fingerprint_invalid:
      'Reviewed fee schedule fingerprint is invalid',
    daily_candidate_background_window_missed:
      "Today's background decision window was missed",
    valuation_missing: 'Valuation missing',
    valuation_snapshot_not_complete:
      'The current account valuation is incomplete',
    portfolio_total_equity_invalid:
      'Total account equity is unavailable from complete evidence',
    promoted_strategy_scan_missing:
      "Today's promoted-strategy scan has not completed",
    promoted_daily_candidate_strategy_missing:
      'No account-qualified promoted strategy is available',
    verified_promoted_strategy_scan_unavailable:
      "Today's verified promoted-strategy scan is unavailable",
    prior_verified_market_date_unavailable:
      'The prior verified trading date is unavailable',
    full_market_universe_snapshot_missing:
      'The full-market universe snapshot is missing',
    verified_market_history_window_incomplete:
      'The verified market-history window is incomplete',
    full_market_daily_receipt_replay_failed:
      'Full-market ingestion receipts could not be verified',
    account_qualification_not_evaluated:
      'The current research batch has not completed account qualification',
    qualification_current_market_date_unavailable:
      'The latest officially verified closed trading date is unavailable',
    qualification_current_market_date_invalid:
      'The latest officially verified closed trading date is invalid',
    qualification_source_market_date_future:
      'The frozen research batch is later than the current verified market date',
    qualification_valuation_snapshot_missing:
      'The current persisted valuation snapshot is missing',
    qualification_valuation_snapshot_not_persisted:
      'The current valuation is not the published immutable snapshot',
    qualification_valuation_trade_date_invalid:
      'The current valuation is not bound to the latest verified closed session',
    qualification_valuation_snapshot_stale:
      'The current valuation is older than the latest verified closed session',
    qualification_valuation_snapshot_future_dated:
      'The current valuation is future-dated',
    qualification_valuation_as_of_invalid:
      'The current valuation timestamp is invalid or future-dated',
    qualification_valuation_or_ledger_not_complete:
      'The current valuation or ledger evidence is incomplete',
    qualification_account_capture_identity_mismatch:
      'The captured account evidence no longer matches the valuation identity',
    qualification_account_evidence_not_authoritative:
      'The current account evidence is not authoritative',
    qualification_reviewed_stock_fee_schedule_invalid:
      'The reviewed stock fee schedule is missing, stale, or unverified',
    qualification_account_capital_evidence_not_passing:
      'The current account-capital evidence did not pass qualification',
    qualification_source_candidate_set_incomplete:
      'The frozen five-candidate research batch is incomplete',
    qualification_source_run_not_complete:
      'The source research run is not complete',
    qualification_source_selection_drift:
      'The frozen source selection has drifted',
    qualification_source_selection_binding_invalid:
      'The normalized source selection binding is invalid',
    qualification_source_candidate_binding_invalid:
      'A frozen source candidate binding is invalid',
    qualification_formula_semantics_changed:
      'Formula semantics changed during account qualification',
    qualification_candidate_replay_incomplete:
      'Account-qualified candidate replay is incomplete',
    no_candidate_passed_account_qualification:
      'No candidate passed account qualification',
  },
  zh: {
    canonical_broker_evidence: 'Canonical 券商证据',
    current_cash_snapshot: '当前资金快照',
    current_position_snapshot: '当前持仓快照',
    itemized_settlement_fees_and_taxes: '逐项结算费用与税',
    position_cost_basis: '持仓成本价',
    freshness_and_ledger_coverage: '新鲜度与账本覆盖',
    reconciliation_gate: '对账门禁',
    known_incomplete_source_reviews: '已知待补证来源复核',
    reviewed_account_and_period_scope: '已复核账户与时段范围',
    account_truth_account_scope_unbound: '券商证据尚未绑定到已复核账户范围',
    account_truth_coverage_window_undeclared:
      '这份券商证据尚未记录已复核覆盖时段',
    account_truth_asset_scope_completeness_unverified:
      '已观察资产不能证明账户资产范围完整',
    account_truth_evidence_scope_missing: '缺少持久化证据范围投影',
    account_truth_evidence_scope_import_mismatch:
      '证据范围与当前账户事实导入不一致',
    account_truth_evidence_scope_event_count_mismatch:
      '持久化事件数量与当前导入不一致',
    account_truth_observed_event_time_invalid: '持久化券商事件包含无效时间',
    account_truth_observed_scope_code_invalid: '持久化券商事件包含无效范围代码',
    account_truth_observed_events_missing: '缺少可用于范围复核的持久化券商事件',
    account_truth_evidence_scope_review_import_mismatch:
      '范围复核指向了不同的账户事实导入',
    account_truth_evidence_scope_review_source_drift:
      '范围复核后券商来源已变化',
    account_truth_evidence_scope_review_observed_drift:
      '范围复核后观察到的券商证据已变化',
    account_truth_evidence_scope_review_revoked: '已复核证据范围已经撤销',
    account_truth_evidence_scope_review_window_incomplete:
      '已复核时段没有包含全部观察到的券商事件',
    account_truth_evidence_scope_review_assets_incomplete:
      '已复核资产范围遗漏了观察到的资产类别',
    account_truth_evidence_scope_review_attestation_missing:
      '缺少完整账户范围确认',
    bind_account_truth_evidence_to_reviewed_account_scope:
      '将证据绑定到已复核账户范围',
    record_reviewed_account_truth_coverage_window:
      '记录这份证据的已复核覆盖时段',
    review_account_truth_asset_scope_completeness:
      '复核账户资产类别是否完整覆盖',
    record_reviewed_account_truth_evidence_scope: '记录已复核账户与时段范围',
    account_truth_gate_pass: '账户事实闸门需要通过',
    account_truth_score_unavailable:
      '缺少已暂存的券商证据，暂时无法计算账户事实分',
    account_truth_evidence_predates_latest_ledger:
      '券商证据早于最新本地账本事实',
    reimport_broker_statement_after_latest_ledger_fact:
      '请导入覆盖最新本地账本事实的券商流水',
    after_cost_report: '成本后报告',
    account_truth: '账户事实',
    cash: '现金',
    cash_missing: '缺少现金凭证',
    commission: '佣金',
    cost_basis: '成本价',
    cost_basis_method: '成本口径',
    cost_basis_missing: '缺少成本价凭证',
    data_refresh: '数据刷新',
    evidence_linked_pnl_pending: '证据已串联，收益待确认',
    fee: '费用',
    estimated_from_linked_fills: '基于已归属成交估算',
    evidence_bound_from_posted_fills: '已绑定入账成交与估值证据',
    ledger_posting_pending: '成交尚未记入生产账本',
    ledger_evidence_drift: '成交与账本证据不一致',
    valuation_snapshot_missing: '缺少持久化估值快照',
    valuation_snapshot_invalid: '持久化估值快照无效',
    valuation_identity_drift: '估值快照身份已漂移',
    inventory_lineage_incomplete: '策略持仓来源链路不完整',
    fee_missing: '缺少费用凭证',
    gross_amount: '成交总额',
    holding_evidence_linked_review_required: '持仓证据已关联，等待复核',
    holding_orders_linked_no_fills: '持仓订单已关联，成交待补齐',
    holding_signal_chain_pending: '持仓信号待补齐订单/成交证据',
    import_and_reconcile_broker_evidence: '导入并对账券商证据',
    provide_cash_snapshot: '提供当前资金快照',
    provide_position_snapshot: '提供当前持仓快照',
    provide_itemized_settlement_or_cash_flow: '提供逐项交割单或资金流水',
    provide_position_cost_basis_evidence: '提供持仓成本价证据',
    refresh_broker_evidence_covering_latest_ledger:
      '更新覆盖最新账本事实的券商证据',
    resolve_account_truth_blockers: '解决账户事实阻断',
    provide_citic_account_truth_evidence_or_reject_source:
      '补充中信账户事实证据或拒绝该来源',
    review_citic_source_query_windows: '逐份复核中信来源的精确查询区间',
    review_citic_source_intake_scan_limit: '复核中信来源扫描上限并恢复完整计数',
    repair_citic_source_intake_metadata_store: '修复中信来源复核元数据存储',
    repair_citic_source_query_window_review_store: '修复中信查询区间复核存储',
    reviewed_query_window_for_source: '已复核这一精确来源的查询区间',
    reviewed_query_window_for_each_source: '已逐份复核全部精确来源的查询区间',
    complete_citic_source_intake_scan: '完整扫描中信来源复核记录',
    contiguous_non_overlapping_reviewed_query_windows:
      '连续且不重叠的已复核查询区间',
    citic_source_follow_up_required: '已知中信来源仍需补证复核',
    citic_source_intake_scan_truncated: '中信来源复核扫描已达到安全上限',
    citic_query_window_batch_calendar_gap: '已复核查询区间之间存在日期缺口',
    citic_query_window_batch_calendar_overlap: '已复核查询区间存在重叠日期',
    citic_query_window_batch_sources_unreviewed:
      '仍有中信来源缺少已复核查询区间',
    citic_source_intake_schema_incomplete: '中信来源复核元数据 schema 不完整',
    citic_source_intake_store_unreadable: '中信来源复核元数据存储不可读',
    citic_source_query_window_review_schema_incomplete:
      '中信查询区间复核 schema 不完整',
    citic_source_query_window_review_store_unreadable:
      '中信查询区间复核存储不可读',
    citic_history_xls_non_financial_activity_ignored:
      '已识别指定交易类非资金活动，未生成券商事件',
    citic_history_xls_invalid_non_financial_activity:
      '指定交易活动不符合已审查的非资金形状',
    review_non_financial_activity: '复核已识别的指定交易类非资金活动',
    versioned_readonly_connector_snapshot: '版本化只读连接器快照',
    reviewed_account_alias_binding: '已复核账户别名绑定',
    provider_source_captured_at: '券商来源采集时间',
    connector_deployment_identity: '连接器部署身份',
    connector_health_evidence: '连接器健康证据',
    current_order_snapshot: '当前订单快照',
    itemized_fill_fees_and_taxes: '逐项成交费用与税',
    link_strategy_signals_orders_fills_and_contribution:
      '串联策略信号、复核、订单、成交与收益归因证据',
    manual_confirm_candidate_actions: '人工确认候选动作',
    manual_confirmation: '人工确认',
    market_data_missing: '缺少行情数据',
    market_data_not_fully_live: '行情需要确认',
    no_intraday_stock_or_etf_action_tasks: '暂无盘中股票或 ETF 候选动作',
    no_linked_fills: '暂无可归属成交',
    net_cash_impact: '净现金影响',
    other_fees: '其他费用',
    out_of_sample_validation: '样本外验证',
    paper_shadow_divergence_review: '模拟复核差异',
    paper_shadow_evidence: '模拟复核证据',
    paper_shadow_review: '模拟复核',
    paper_shadow_evidence_required_before_manual_confirmation:
      '人工确认前需要补齐模拟复核证据',
    broker_cost_basis_method: '券商成本口径',
    karkinos_cost_basis_method: '本地成本口径',
    broker_remaining_cost: '券商剩余持仓成本',
    moving_average_buy_cost: '移动平均买入成本',
    comparison_unit: '对比单位',
    per_share_cost_basis: '单股成本价',
    comparison_precision: '对比精度',
    decimal_string_no_rounding: '原始小数值',
    precision_limitation: '精度限制',
    broker_display_precision_fee_allocation_tax_timing_transfer_fee_rounding:
      '券商显示精度、费用分摊、税费确认与过户费舍入可能不同',
    position: '持仓',
    position_missing: '缺少持仓凭证',
    preview_import_and_reconcile_broker_evidence: '预览券商凭证导入并完成对账',
    quote_older_than_expected_session: '行情早于预期交易时段',
    refresh_market_data: '刷新行情',
    refresh_or_confirm_market_data: '刷新或确认行情',
    refresh_quotes_or_check_source: '刷新行情或检查数据源',
    resolve_account_truth_before_rebalance: '先解决账户事实再再平衡',
    resolve_upstream_workflow_blockers: '先处理上游阻断',
    review_position_difference: '复核持仓差异',
    review_cash_difference: '复核现金差异',
    review_cost_basis_difference: '复核成本价差异',
    review_fee_difference: '复核费用差异',
    review_net_cash_impact_difference: '复核净现金影响差异',
    review_tax_difference: '复核税费差异',
    review_trade_gross_amount_difference: '复核成交总额差异',
    review_transfer_fee_difference: '复核过户费差异',
    review_paper_shadow_evidence: '查看模拟复核证据',
    review_blocked_risk_gate: '复核被风控阻断的原因',
    review_risk_blockers: '复核风控阻断',
    risk_gate_blocked: '风控闸门正在阻断动作',
    risk_gate_not_checked: '仍有动作未完成风控检查',
    risk_review: '风险复核',
    'order.fill.recorded': '成交已记录',
    'order.recorded': '订单已记录',
    'order.shadow_divergence_reviewed': '模拟复核差异已记录',
    'order.status_changed': '订单状态已更新',
    'order.submitted': '订单已提交',
    'signal.review.recorded': '信号复核已记录',
    'task.action.created': '动作任务已创建',
    'task.action.status_changed': '动作任务状态已更新',
    'task_run.completed': '任务运行已完成',
    'task_run.started': '任务运行已开始',
    'risk.signal.recorded': '风控信号已记录',
    run_pre_trade_risk_gate: '运行下单前风控',
    run_first_sync: '配置数据源或执行首次同步',
    risk_block_evidence: '风控阻断证据',
    stamp_tax: '印花税',
    strategy_evidence: '策略证据',
    strategy_attribution_evidence: '策略归因证据',
    strategy_attribution_not_ready: '策略归因证据尚未就绪',
    tax: '税费',
    trade_gross_amount: '成交总额',
    transfer_fee: '过户费',
    upstream_workflow_blockers: '仍有上游阻断未处理',
    unresolved_position_difference: '存在未解决的持仓差异',
    decision_generated_outside_reviewed_window: '决策生成时间不在已复核窗口内',
    plan_generated_outside_reviewed_window: '交易计划生成时间不在已复核窗口内',
    account_truth_promotion_status_not_clear: '账户事实尚未通过策略晋级审查',
    account_truth_gate_not_pass: '账户事实门禁未通过',
    account_truth_not_fresh: '账户事实快照已过期',
    account_truth_not_bound_to_plan_date: '账户事实未绑定到当日运行日期',
    account_truth_age_exceeds_reviewed_limit: '账户事实超过已复核新鲜度上限',
    account_truth_too_old_for_decision: '生成决策时账户事实已经过期',
    market_quote_timestamp_missing_or_invalid: '持久化行情时间缺失或无效',
    daily_candidate_strategy_candidate_missing: '缺少已晋级策略候选',
    reviewed_fee_schedule_review_missing: '缺少真实费用方案复核记录',
    reviewed_fee_schedule_not_active: '真实费用方案尚未生效',
    reviewed_fee_schedule_review_fingerprint_invalid: '真实费用复核指纹无效',
    daily_candidate_background_window_missed: '已错过今日后台决策窗口',
    valuation_missing: '缺少估值',
    valuation_snapshot_not_complete: '当前账户估值证据不完整',
    portfolio_total_equity_invalid: '无法从完整证据得到账户总权益',
    promoted_strategy_scan_missing: '今天的已晋级策略扫描尚未完成',
    promoted_daily_candidate_strategy_missing:
      '当前没有通过账户资格并晋级的策略',
    verified_promoted_strategy_scan_unavailable:
      '今天缺少可验证的已晋级策略扫描',
    prior_verified_market_date_unavailable: '缺少上一已验证交易日',
    full_market_universe_snapshot_missing: '缺少全市场标的快照',
    verified_market_history_window_incomplete: '已验证行情历史窗口不完整',
    full_market_daily_receipt_replay_failed: '全市场数据采集回执校验失败',
    account_qualification_not_evaluated: '当前研究批次尚未完成账户资格复核',
    qualification_current_market_date_unavailable:
      '缺少最新官方验证的已收盘交易日',
    qualification_current_market_date_invalid: '最新已验证交易日无效',
    qualification_source_market_date_future:
      '冻结研究批次晚于当前已验证行情日期',
    qualification_valuation_snapshot_missing: '缺少当前持久化估值快照',
    qualification_valuation_snapshot_not_persisted:
      '当前估值不是已发布的不可变快照',
    qualification_valuation_trade_date_invalid:
      '当前估值未绑定到最新已验证收盘交易日',
    qualification_valuation_snapshot_stale: '当前估值早于最新已验证收盘交易日',
    qualification_valuation_snapshot_future_dated: '当前估值日期来自未来',
    qualification_valuation_as_of_invalid: '当前估值时间无效或来自未来',
    qualification_valuation_or_ledger_not_complete: '当前估值或账本证据不完整',
    qualification_account_capture_identity_mismatch:
      '账户证据与当前估值身份不再一致',
    qualification_account_evidence_not_authoritative:
      '当前账户证据不是权威证据',
    qualification_reviewed_stock_fee_schedule_invalid:
      '股票真实费用方案缺失、过期或未验证',
    qualification_account_capital_evidence_not_passing:
      '当前账户资本证据未通过资格门禁',
    qualification_source_candidate_set_incomplete: '冻结的五候选研究批次不完整',
    qualification_source_run_not_complete: '源研究运行尚未完成',
    qualification_source_selection_drift: '冻结的源选择已发生漂移',
    qualification_source_selection_binding_invalid: '归一化源选择绑定无效',
    qualification_source_candidate_binding_invalid: '冻结的源候选绑定无效',
    qualification_formula_semantics_changed:
      '账户资格复跑期间 Formula 语义发生变化',
    qualification_candidate_replay_incomplete: '账户资格候选复跑未完整完成',
    no_candidate_passed_account_qualification: '没有候选通过账户资格复核',
  },
};
