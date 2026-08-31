export const gateLabels: Record<string, { zh: string; en: string }> = {
  automation_policy: { zh: '安全策略', en: 'Safe policy' },
  decision_plan: { zh: '决策与计划', en: 'Decision and plan' },
  account_truth: { zh: '账户事实', en: 'Account Truth' },
  market_data: { zh: '冻结行情', en: 'Frozen market' },
  strategy: { zh: '晋级策略', en: 'Promoted strategy' },
  reviewed_fees: { zh: '真实费用', en: 'Reviewed fees' },
  execution_closure: { zh: '前序执行闭环', en: 'Prior closure' },
  runtime_window: { zh: '运行窗口', en: 'Runtime window' },
  source_evidence: { zh: '预检证据源', en: 'Preflight sources' },
  ready: { zh: '下一步', en: 'Next step' },
};
export const actionLabels: Record<string, { zh: string; en: string }> = {
  restore_paper_shadow_only_automation_policy: {
    zh: '恢复仅 paper/shadow 的安全策略',
    en: 'Restore the paper/shadow-only safety policy',
  },
  complete_current_account_truth_evidence_review: {
    zh: '完成当前 Account Truth 证据与范围复核',
    en: 'Complete the current Account Truth evidence and scope review',
  },
  review_account_specific_fee_schedule: {
    zh: '复核账户专属费用版本',
    en: 'Review the account-specific fee schedule',
  },
  promote_evidence_bound_strategy_for_paper_shadow: {
    zh: '人工晋级一项证据绑定策略到 paper/shadow',
    en: 'Promote one evidence-bound strategy to paper/shadow',
  },
  complete_plan_paper_actual_reconciliation: {
    zh: '完成 plan / paper / actual 对账闭环',
    en: 'Complete plan / paper / actual reconciliation',
  },
  persist_current_market_quotes_for_reviewed_window: {
    zh: '在复核窗口持久化当前行情',
    en: 'Persist current quotes in the reviewed window',
  },
  rebuild_decision_and_plan_in_reviewed_window: {
    zh: '在复核窗口重建 Decision 与计划',
    en: 'Rebuild the Decision and plan in the reviewed window',
  },
  prepare_current_evidence_for_next_reviewed_window: {
    zh: '为下一个复核窗口准备当前证据',
    en: 'Prepare current evidence for the next reviewed window',
  },
  keep_monitor_running_and_wait_for_reviewed_window: {
    zh: '保持监控并等待复核窗口',
    en: 'Keep the monitor running and wait for the reviewed window',
  },
  wait_for_next_verified_trading_day: {
    zh: '等待下一个已验证交易日',
    en: 'Wait for the next verified trading day',
  },
  review_persisted_daily_result: {
    zh: '复核已持久化的当日结果',
    en: 'Review the persisted daily result',
  },
  restore_daily_candidate_runtime_before_reviewed_window: {
    zh: '在复核窗口前恢复每日候选运行状态',
    en: 'Restore daily-candidate runtime before the reviewed window',
  },
  restore_persisted_preflight_sources_before_next_window: {
    zh: '在下个窗口前恢复持久化预检证据源',
    en: 'Restore persisted preflight sources before the next window',
  },
  allow_single_claimed_fail_closed_background_attempt: {
    zh: '等待单次、已认领且 fail-closed 的后台尝试',
    en: 'Await one claimed, fail-closed background attempt',
  },
  start_one_canonical_daily_candidate_attempt: {
    zh: '启动一次 canonical 每日候选尝试',
    en: 'Start one canonical daily-candidate attempt',
  },
};
export const evidenceLabels: Record<string, { zh: string; en: string }> = {
  persisted_paper_shadow_only_automation_policy: {
    zh: '已持久化的仅 paper/shadow 自动化策略',
    en: 'Persisted paper/shadow-only automation policy',
  },
  manual_confirmation_and_kill_switch_controls: {
    zh: '人工确认与 kill switch 控制',
    en: 'Manual-confirmation and kill-switch controls',
  },
  current_cash_snapshot_with_aware_timestamp_and_cash_balance: {
    zh: '当前 cash_snapshot：含时区时间戳与 cash_balance',
    en: 'Current cash_snapshot with an aware timestamp and cash_balance',
  },
  current_position_snapshots_with_symbol_asset_currency_quantity_and_cost_basis:
    {
      zh: '当前 position_snapshot：含 symbol、asset_class、currency、position_quantity 与 cost_basis',
      en: 'Current position_snapshot rows with symbol, asset_class, currency, position_quantity, and cost_basis',
    },
  itemized_trade_rows_with_quantity_price_gross_fee_tax_transfer_fee_and_net_amount:
    {
      zh: '逐笔成交：quantity、price、gross_amount、fee、tax、transfer_fee 与 net_amount',
      en: 'Itemized trades with quantity, price, gross_amount, fee, tax, transfer_fee, and net_amount',
    },
  reviewed_source_hash_window_scope_and_completeness_attestations: {
    zh: '每份来源的脱敏哈希、查询窗口、账户/市场/资产/业务范围、无额外筛选与完整返回复核',
    en: 'Per-source sanitized hash, query window, scope, no-extra-filter, and complete-return review',
  },
  current_ledger_cutoff_and_reconciliation_evidence: {
    zh: '当前账本截止点与 Account Truth 对账证据',
    en: 'Current ledger cutoff and Account Truth reconciliation evidence',
  },
  account_specific_commission_minimum_stamp_tax_transfer_fee_and_other_fee_terms:
    {
      zh: '账户专属佣金率/最低佣金、印花税、过户费及其他费用条款',
      en: 'Account-specific commission/minimum, stamp tax, transfer fee, and other-fee terms',
    },
  historical_buy_and_sell_itemized_fee_components: {
    zh: '历史买入与卖出的逐项费用证据',
    en: 'Historical buy and sell itemized fee evidence',
  },
  human_accepted_fee_effective_date_window: {
    zh: '人工接受且可撤销的费用生效日期窗口',
    en: 'Human-accepted, revocable fee effective-date window',
  },
  five_sequential_research_iterations: {
    zh: '5 轮前后依赖的顺序研究迭代（不是并发 5 次）',
    en: 'Five dependent sequential research iterations, not five parallel calls',
  },
  deterministic_local_backtest_and_promotion_evidence: {
    zh: '本地确定性回测与晋级证据',
    en: 'Deterministic local backtest and promotion evidence',
  },
  content_addressed_daily_strategy_backup: {
    zh: '内容寻址的当日策略备份',
    en: 'Content-addressed daily strategy backup',
  },
  bounded_revocable_human_promotion_review: {
    zh: '明确有界、可撤销的人工晋级复核',
    en: 'Bounded, revocable human promotion review',
  },
  persisted_plan_paper_and_actual_execution_records: {
    zh: '已持久化的 plan / paper / actual 记录',
    en: 'Persisted plan, paper, and actual records',
  },
  per_order_terminal_and_ledger_reconciliation: {
    zh: '逐单终态与账本对账',
    en: 'Per-order terminal and ledger reconciliation',
  },
  persisted_trusted_quote_with_source_price_and_aware_timestamp: {
    zh: '含来源、价格与时区时间戳的可信持久化行情',
    en: 'Persisted trusted quote with source, price, and aware timestamp',
  },
  persisted_same_day_decision_and_trading_plan: {
    zh: '同日持久化 Decision 与交易计划',
    en: 'Persisted same-day Decision and trading plan',
  },
  matching_account_market_strategy_fee_and_closure_bindings: {
    zh: '一致的账户、行情、策略、费用及闭环绑定',
    en: 'Matching account, market, strategy, fee, and closure bindings',
  },
  loaded_local_daily_candidate_service_and_live_monitor_task: {
    zh: '已加载的本地每日候选服务与存活监控 task',
    en: 'Loaded local daily-candidate service and live monitor task',
  },
  reviewed_exchange_calendar_and_current_decision_window: {
    zh: '已复核交易所日历与当前决策窗口',
    en: 'Reviewed exchange calendar and current decision window',
  },
  readable_persisted_decision_plan_fee_closure_and_runtime_sources: {
    zh: '可读取的持久化 Decision、计划、费用、闭环与运行时来源',
    en: 'Readable persisted Decision, plan, fee, closure, and runtime sources',
  },
  persisted_current_preflight_facts: {
    zh: '已持久化且当前有效的全部预检事实',
    en: 'Persisted current facts for every preflight gate',
  },
};
export const completionLabels: Record<string, { zh: string; en: string }> = {
  broker_submission_remains_disabled: {
    zh: '券商提交保持禁用',
    en: 'Broker submission remains disabled',
  },
  manual_confirmation_remains_required: {
    zh: '人工确认保持必需',
    en: 'Manual confirmation remains required',
  },
  allowed_modes_exclude_live_like_execution: {
    zh: '允许模式不包含 live-like 执行',
    en: 'Allowed modes exclude live-like execution',
  },
  cash_and_position_snapshots_share_current_shanghai_date: {
    zh: '现金与持仓快照属于同一当前上海市场日',
    en: 'Cash and position snapshots share the current Shanghai market date',
  },
  snapshots_are_no_more_than_86400_seconds_old_and_not_before_latest_event: {
    zh: '快照不超过 86400 秒，且不早于最新账户事件',
    en: 'Snapshots are at most 86400 seconds old and not before the latest account event',
  },
  account_truth_covers_latest_ledger_cutoff: {
    zh: 'Account Truth 覆盖最新持久化账本截止点',
    en: 'Account Truth covers the latest persisted ledger cutoff',
  },
  cash_position_fee_and_cost_basis_pass_with_zero_unresolved_mismatches: {
    zh: '现金、持仓、费用与成本基础全部通过，未解决差异为 0',
    en: 'Cash, position, fee, and cost-basis checks pass with zero unresolved mismatches',
  },
  private_xls_content_and_account_identifiers_remain_unstored: {
    zh: '不写入原始 XLS 内容或私有账户标识',
    en: 'Raw XLS content and private account identifiers remain unstored',
  },
  historical_buy_and_sell_fee_component_reconciliation_passes: {
    zh: '历史买卖双向的费用分项对账通过',
    en: 'Historical buy and sell fee-component reconciliation passes',
  },
  action_date_is_inside_accepted_fee_window: {
    zh: '候选操作日期位于已接受费用窗口内',
    en: 'The candidate action date is inside the accepted fee window',
  },
  fee_review_matches_current_account_truth_and_strategy_bindings: {
    zh: '费用复核与当前 Account Truth、策略绑定一致',
    en: 'Fee review matches current Account Truth and strategy bindings',
  },
  fee_review_is_bounded_and_revocable: {
    zh: '费用复核明确有界且可撤销',
    en: 'Fee review is bounded and revocable',
  },
  each_iteration_binds_previous_formula_metrics_blockers_and_critique: {
    zh: '第 N+1 轮绑定第 N 轮公式、指标、阻断项与 critique 指纹',
    en: 'Iteration N+1 binds iteration N formula, metrics, blockers, and critique fingerprint',
  },
  research_policy_authorizes_exactly_five_iterations_and_ten_provider_calls: {
    zh: '人工研究策略明确授权恰好 5 轮、最多 10 次 provider 调用',
    en: 'Human-reviewed research policy authorizes exactly five iterations and at most ten provider calls',
  },
  winner_passes_every_deterministic_gate_or_incumbent_remains_unchanged: {
    zh: '优胜者通过全部确定性门槛；否则保留原人工批准策略',
    en: 'The winner passes every deterministic gate; otherwise the human-approved incumbent is unchanged',
  },
  promoted_strategy_replays_from_frozen_data_and_current_fee_review: {
    zh: '晋级策略可从冻结数据与当前费用复核重放',
    en: 'The promoted strategy replays from frozen data and the current fee review',
  },
  live_like_execution_remains_disabled: {
    zh: 'live-like 执行保持禁用',
    en: 'Live-like execution remains disabled',
  },
  every_prior_required_order_is_reconciled_or_explicitly_not_required: {
    zh: '每个前序必要订单均已对账或明确标为不需要',
    en: 'Every prior required order is reconciled or explicitly not required',
  },
  unresolved_or_drifted_execution_evidence_count_is_zero: {
    zh: '未解决或漂移的执行证据数量为 0',
    en: 'Unresolved or drifted execution evidence count is zero',
  },
  quote_is_bound_to_plan_date_and_not_after_decision_time: {
    zh: '行情绑定计划日期且时间不晚于 Decision',
    en: 'Quote is bound to the plan date and not after Decision time',
  },
  quote_age_at_decision_is_no_more_than_300_seconds: {
    zh: 'Decision 时行情年龄不超过 300 秒',
    en: 'Quote age at Decision time is at most 300 seconds',
  },
  decision_and_plan_are_rebuilt_inside_reviewed_window: {
    zh: 'Decision 与计划在已复核窗口内重建',
    en: 'Decision and plan are rebuilt inside the reviewed window',
  },
  decision_plan_bindings_replay_without_drift: {
    zh: 'Decision/计划绑定可无漂移重放',
    en: 'Decision/plan bindings replay without drift',
  },
  launch_agent_and_process_liveness_are_both_confirmed: {
    zh: 'LaunchAgent 已加载且进程存活均得到确认',
    en: 'Both LaunchAgent loading and process liveness are confirmed',
  },
  exactly_one_fail_closed_attempt_is_due_in_reviewed_window: {
    zh: '复核窗口内仅有一次到期且 fail-closed 的尝试',
    en: 'Exactly one fail-closed attempt is due in the reviewed window',
  },
  runtime_liveness_does_not_claim_financial_readiness: {
    zh: '运行存活不被当作财务就绪',
    en: 'Runtime liveness does not claim financial readiness',
  },
  all_preflight_sources_are_readable_and_contract_valid: {
    zh: '全部预检来源均可读取且契约有效',
    en: 'All preflight sources are readable and contract-valid',
  },
  source_restoration_does_not_mutate_financial_state: {
    zh: '恢复来源不修改财务状态',
    en: 'Source restoration does not mutate financial state',
  },
  start_only_one_canonical_risk_and_paper_shadow_attempt: {
    zh: '只启动一次 canonical 风控与 paper/shadow 尝试',
    en: 'Start only one canonical risk and paper/shadow attempt',
  },
  separate_post_shadow_gate_and_human_confirmation_remain_required: {
    zh: '后置生产门禁与独立人工确认仍然必需',
    en: 'A separate post-shadow gate and human confirmation remain required',
  },
};
export const gateReviewPaths: Record<string, string> = {
  account_truth: '/account-truth',
  reviewed_fees: '/account-truth',
  strategy: '/ai-research',
  execution_closure: '/operations',
  market_data: '/decision',
  decision_plan: '/decision',
  runtime_window: '/operations',
  source_evidence: '/operations',
  automation_policy: '/operations',
  ready: '/decision',
};
