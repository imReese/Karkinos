export const chronologicalCopy = {
  en: {
    enable: 'Select on training data, then test chronologically',
    requires:
      'Select the dual moving-average strategy and a saved immutable Dataset to use this mode.',
    testStart: 'Test start date',
    invalidDate:
      'Choose a test start date after the Dataset start and no later than its end.',
    insufficientSessions:
      'The test start must be a recorded trading session for every symbol, with at least the longest moving-average window plus one earlier session and two sessions in the test period. Adjust the split or Dataset range.',
    scoreUnavailable:
      'A training score is unavailable, so no test candidate could be selected. Check the training data and ranking metric.',
    procedure:
      'Candidates are ranked using only the earlier training period. Only the winner is then evaluated on the later test period with fresh initial cash; prior data warms strategy state without carrying positions or orders.',
    boundary:
      'This is exploratory validation. Reusing or inspecting the test period does not make it an untouched final holdout. No AI provider is required.',
    run: 'Run training selection and test',
    trainingTitle: 'Training-period rankings',
    trainingScores:
      'These scores use training data only. Test results do not select or re-rank candidates.',
    testTitle: 'Selected candidate · test result',
    selectedTraining: 'Selected training report',
    savedTest: 'Saved test report',
    loading: 'Loading the saved test report…',
    failed:
      'The selected test report could not be loaded. Refresh to read its saved evidence.',
    refresh: 'Refresh test report',
    performance: 'Recorded performance window',
    training: 'Training period',
    test: 'Test period',
    metricDates: 'Actual metric dates',
    evaluationDates: 'Requested evaluation period',
    datasetDates: 'Full source Dataset period',
    historyEnd: 'History available through',
    warmup:
      'Independent initial cash; warm-up updates strategy state only and carries no positions or pending orders.',
    evidence: 'Chronological evaluation details',
    experiment: 'Experiment',
    fingerprint: 'Evaluation fingerprint',
    source: 'Source Dataset',
    snapshot: 'Source snapshot',
    noDates: 'No recorded metric dates',
  },
  zh: {
    enable: '先用训练期选参，再按时间顺序测试',
    requires: '此模式需要选择双均线策略和已保存的不可变 Dataset。',
    testStart: '测试起始日',
    invalidDate: '测试起始日须晚于 Dataset 起始日，且不晚于结束日。',
    insufficientSessions:
      '测试起始日须为所有标的均有记录的交易日；此前至少需要最长均线窗口加一个交易日，测试期至少需要两个交易日。请调整切分日期或 Dataset 区间。',
    scoreUnavailable:
      '训练分数不可用，无法选出测试候选。请检查训练数据和排序指标。',
    procedure:
      '候选参数只按较早的训练期排名；仅将胜出参数用于后续测试期。测试从独立初始资金开始，先前数据仅预热策略状态，不继承持仓或订单。',
    boundary:
      '这是探索性验证。反复使用或查看测试期，不会使其成为未接触的最终留出集。本流程不依赖 AI 服务。',
    run: '运行训练选参与后续测试',
    trainingTitle: '训练期排名',
    trainingScores: '这些分数仅来自训练数据；测试结果不参与选参或重新排名。',
    testTitle: '已选候选 · 测试结果',
    selectedTraining: '选中的训练报告',
    savedTest: '已保存测试报告',
    loading: '正在读取已保存测试报告…',
    failed: '无法读取选中的测试报告，请刷新以读取已保存证据。',
    refresh: '刷新测试报告',
    performance: '已记录绩效区间',
    training: '训练期',
    test: '测试期',
    metricDates: '实际指标日期',
    evaluationDates: '请求的评估区间',
    datasetDates: '来源 Dataset 完整区间',
    historyEnd: '历史数据截至',
    warmup: '使用独立初始资金；预热只更新策略状态，不继承持仓或待执行订单。',
    evidence: '时间顺序评估详情',
    experiment: '实验身份',
    fingerprint: '评估指纹',
    source: '来源 Dataset',
    snapshot: '来源快照',
    noDates: '未记录指标日期',
  },
};
