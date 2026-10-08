import { observationHealthCopy } from './copy-observation-health';

export const observationCopy = {
  en: {
    title: 'Independent forward observation',
    detail:
      'Freeze this saved research result, publish targets using new verified data, and measure subsequent price changes.',
    boundary:
      'Target-only shadow: no account, orders or fills. Results are unadjusted price responses, exclude costs, dividends and bonus shares, and are not NAV or investment returns.',
    start: 'Start observation',
    setup: 'New observation settings',
    horizon: 'Outcome horizon (trading sessions)',
    symbolLimit: 'Maximum symbol weight (0–1)',
    grossLimit: 'Maximum total weight (0–1)',
    symbolCap: 'Maximum symbol weight',
    grossCap: 'Maximum total weight',
    invalid:
      'Use an integer horizon from 1 to 60 and weights greater than 0 and at most 1.',
    unsupported:
      'Start from a saved dual moving-average, ETF rotation or Formula research definition. Choose verified warmup data for a new observation.',
    select: 'Saved observations for this report',
    none: 'No saved observations for this report.',
    loading: 'Loading saved observations…',
    loadFailed: 'Could not load observations. Refresh to retry.',
    refresh: 'Refresh saved evidence',
    active: 'Publishing enabled',
    paused: 'Publishing paused',
    started: 'Started',
    sourceUnknown:
      'The original backtest did not bind its code version. This observation freezes the current implementation as a new research version.',
    pitUnknown:
      'The frozen research universe does not establish historical point-in-time membership or freedom from survivorship bias.',
    dataset: 'Verified dataset for this observation',
    choose: 'Choose a saved dataset',
    datasetHint:
      'Use the same instruments and history start, extended through the latest closed session. Prepare and verify a new Dataset in the research data controls when needed.',
    noDatasets:
      'No matching verified datasets. Prepare and verify the required history, then refresh.',
    datasetFailed: 'Could not load saved datasets. Refresh to retry.',
    advance: 'Publish targets and measure outcomes',
    measure: 'Measure existing publications',
    pause: 'Pause new publications',
    pauseDetail:
      'Pausing preserves history and still allows existing publications to be measured with later data.',
    saved: 'Saved. The view now shows persisted observation history.',
    busy: 'Saving…',
    noPublications:
      'No targets published yet. Select current verified data and publish the first observation.',
    awaiting: 'Awaiting future data',
    measured: 'Measured price response',
    decision: 'Decision session',
    published: 'Published',
    endpoints: 'Future close-to-close interval',
    riskAllowed: 'Within target limits',
    riskBlocked: 'Target risk blocked',
    symbol: 'Symbol',
    action: 'Forecast',
    target: 'Approved target',
    delta: 'Weight change',
    contribution: 'Price contribution',
    enter: 'Enter',
    exit: 'Exit',
    hold: 'Hold',
    provenance: 'Dataset identities and timing',
    sourceDataset: 'Frozen source dataset',
    publicationDataset: 'Publication dataset',
    outcomeDataset: 'Outcome dataset',
    measuredAt: 'Measured at',
    actionsKnown:
      'Corporate-action evidence is attached; its cash and share effects are excluded from this price-only measurement.',
    failure:
      'The observation could not advance. Check the dataset and saved state, then retry.',
    stale:
      'This observation changed in another session. Refresh its saved state before retrying.',
    codeChanged:
      'The implementation changed after this observation was frozen. Preserve its history and start a new observation from the saved report.',
    calendar:
      'Verified trading-calendar evidence is missing for the observation interval. Verify the required years, then retry.',
    datasetInvalid:
      'This dataset does not cover the exact frozen universe and full history through the latest closed session. Prepare and verify a matching dataset.',
    notAvailable:
      'Some data or verification was not available at evaluation time. Wait until the evidence is available, then retry.',
    alreadyPublished:
      'This session already has a frozen publication. Existing outcomes are still measured when their future data is available.',
    publicationPaused:
      'New publications are paused; existing publications remain eligible for measurement.',
    capacity:
      'The active-observation limit has been reached. Pause an observation before starting another.',
    sourceInvalid:
      'This saved result cannot supply a supported, intact strategy definition. Check its saved parameters and typed instruments before starting a new observation.',
  },
  zh: {
    title: '独立前向观察',
    detail:
      '冻结这份已保存的研究结果，用新增核验数据发布目标，再观察之后的价格变化。',
    boundary:
      '仅观察目标权重，不建立账户、订单或成交。结果为不复权价格响应，未计成本、分红和送转，不是净值或投资收益。',
    start: '开始观察',
    setup: '新观察设置',
    horizon: '结果观察跨度（交易日）',
    symbolLimit: '单标的权重上限（0–1）',
    grossLimit: '总权重上限（0–1）',
    symbolCap: '单标的权重上限',
    grossCap: '总权重上限',
    invalid: '观察跨度须为 1 至 60 的整数，权重须大于 0 且不超过 1。',
    unsupported:
      '请从已保存的双均线、ETF 轮动报告或 Formula 研究定义开始，并为新观察选择已核验的预热数据。',
    select: '本报告已保存的观察',
    none: '本报告尚无已保存的观察。',
    loading: '正在读取已保存的观察…',
    loadFailed: '无法读取观察记录，请刷新重试。',
    refresh: '刷新已保存证据',
    active: '允许发布',
    paused: '发布已暂停',
    started: '开始时间',
    sourceUnknown:
      '原回测未绑定代码版本。本次观察将当前实现冻结为新的研究版本。',
    pitUnknown:
      '冻结的研究标的池不能证明历史时点成分正确，也不能排除幸存者偏差。',
    dataset: '用于本次观察的核验数据集',
    choose: '选择已保存的数据集',
    datasetHint:
      '须保持相同标的与历史起点，并延长至最近已收盘交易日。需要新数据时，请在研究数据控件中准备并核验 Dataset。',
    noDatasets: '没有匹配的核验数据集。请准备并核验所需历史，再刷新。',
    datasetFailed: '无法读取已保存数据集，请刷新重试。',
    advance: '发布目标并评估结果',
    measure: '评估已有发布',
    pause: '暂停新增发布',
    pauseDetail: '暂停会保留历史；仍可使用后续数据评估已发布的观察。',
    saved: '已保存，当前显示持久记录。',
    busy: '正在保存…',
    noPublications: '尚未发布目标。请选择当前核验数据，发布首次观察。',
    awaiting: '等待未来数据',
    measured: '已测量价格响应',
    decision: '决策交易日',
    published: '发布时间',
    endpoints: '未来收盘价比较区间',
    riskAllowed: '目标在风险限额内',
    riskBlocked: '目标风险受阻',
    symbol: '标的',
    action: '预测',
    target: '批准目标权重',
    delta: '权重变动',
    contribution: '价格贡献',
    enter: '进入',
    exit: '退出',
    hold: '保持',
    provenance: '数据集身份与时间',
    sourceDataset: '冻结来源数据集',
    publicationDataset: '发布使用的数据集',
    outcomeDataset: '结果使用的数据集',
    measuredAt: '测量时间',
    actionsKnown: '已附公司行动证据；此价格测量仍未计入相应现金和股份权益。',
    failure: '观察未能推进。请检查数据集和已保存状态后重试。',
    stale: '其他会话已修改此观察。请刷新已保存状态后重试。',
    codeChanged:
      '当前实现与观察冻结时不同。请保留历史，并从已保存报告开始新观察。',
    calendar: '观察区间缺少核验交易日历。请核验相关年份后重试。',
    datasetInvalid:
      '数据集未完整覆盖冻结标的、固定历史起点和最近已收盘交易日。请准备并核验匹配的数据集。',
    notAvailable: '部分数据或核验证据在评估时尚不可得。请等待证据可用后重试。',
    alreadyPublished:
      '本交易日已发布并冻结；未来数据可用时，仍会评估已有发布的结果。',
    publicationPaused: '新增发布已暂停，已有发布仍可评估。',
    capacity: '活跃观察已达上限。请先暂停一个观察，再开始新的观察。',
    sourceInvalid:
      '这份报告无法提供完整的策略定义。请核对保存的参数和标的类型，再开始新观察。',
  },
};

export function observationError(error: unknown, locale: 'en' | 'zh') {
  const labels = observationCopy[locale];
  const code =
    typeof error === 'string'
      ? error
      : error instanceof Error
        ? error.message
        : '';
  if (code.includes('version_conflict') || code.includes('request_conflict'))
    return labels.stale;
  if (code === 'observation_health_rule_paused')
    return observationHealthCopy[locale].paused;
  if (code === 'health_policy_invalid')
    return observationHealthCopy[locale].invalid;
  if (code === 'observation_code_changed') return labels.codeChanged;
  if (code.includes('calendar')) return labels.calendar;
  if (code === 'observation_source_formal_dataset_required')
    return locale === 'zh'
      ? '原报告未绑定正式数据集。请为新观察选择或准备独立预热数据。'
      : 'The original report has no formal Dataset. Choose or prepare separate warmup data for this new observation.';
  if (code === 'observation_session_already_published')
    return labels.alreadyPublished;
  if (
    code === 'observation_publication_paused' ||
    code === 'research_observation_paused'
  )
    return labels.publicationPaused;
  if (code.includes('active_limit')) return labels.capacity;
  if (code.includes('not_available') || code.includes('in_future'))
    return labels.notAvailable;
  if (
    code.includes('dataset_') ||
    code.includes('history_') ||
    code.includes('bar_')
  )
    return labels.datasetInvalid;
  if (
    code.includes('source_') ||
    code.includes('strategy_') ||
    code.includes('formula_')
  )
    return labels.sourceInvalid;
  return labels.failure;
}
