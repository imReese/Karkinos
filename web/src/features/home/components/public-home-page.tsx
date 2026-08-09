import {
  ArrowRight,
  Languages,
  LockKeyhole,
  Moon,
  ShieldCheck,
  Sun,
} from 'lucide-react';
import { useEffect, useState, type KeyboardEvent } from 'react';
import { Link } from '@tanstack/react-router';

import { KarkinosMark } from '../../../app/components/brand/karkinos-mark';
import { usePreferences } from '../../../app/preferences';

const publicHomeCopy = {
  en: {
    skip: 'Skip to main content',
    brandLabel: 'Karkinos home',
    navLabel: 'Public navigation',
    sectionNavLabel: 'Page sections',
    nav: {
      product: 'Product',
      principles: 'Trust',
      workflow: 'Workflow',
      docs: 'Docs',
    },
    enter: 'Open private workbench',
    enterShort: 'Workbench',
    language: 'Switch to Chinese',
    lightTheme: 'Switch to Latte theme',
    darkTheme: 'Switch to Mocha theme',
    hero: {
      eyebrow: 'China market · Personal quant workspace',
      title: 'Every decision should leave evidence.',
      body: 'Karkinos connects account truth, research, risk, and human review into one auditable path. Evidence moves first; authority stays explicit.',
      explore: 'Explore the workflow',
    },
    evidence: {
      eyebrow: 'Product trace · No account data',
      title: 'Evidence advances. Authority stays explicit.',
      routeLabel: 'Public-to-private route',
      publicRoute: 'Public overview',
      privateRoute: 'Private workbench',
      flowLabel: 'Decision evidence path',
      previewLabel: 'Workbench structure',
      caption:
        'Structural product proof only. It contains no account, return, order, or execution data.',
      metrics: [
        {
          label: 'Account facts',
          value: 'Consistent',
          detail: 'One account view',
        },
        {
          label: 'Evidence quality',
          value: 'Visible',
          detail: 'Freshness and gaps',
        },
        {
          label: 'Authority',
          value: 'Human',
          detail: 'Read and review',
        },
      ],
      priority: {
        eyebrow: 'Operator priority',
        title: 'Resolve the highest blocker first.',
        reasonLabel: 'Why',
        reason: 'Missing or stale evidence stays visible.',
        nextLabel: 'Safe next step',
        next: 'Open the exact evidence surface.',
      },
      rows: [
        {
          label: 'Account truth',
          detail: 'One account view',
          state: 'Saved',
        },
        {
          label: 'Research',
          detail: 'Data and result linked',
          state: 'Traceable',
        },
        {
          label: 'Risk',
          detail: 'Threshold and reason',
          state: 'Evaluated',
        },
        {
          label: 'Human review',
          detail: 'Permission stays explicit',
          state: 'Required',
        },
      ],
      outcomeLabel: 'Default authority',
      outcome: 'Read and review only',
      outcomeNote:
        'No order placement, cancellation, recovery, or capital expansion by default.',
    },
    proof: {
      eyebrow: 'Product proof',
      title: 'See the fact. See the boundary.',
      body: 'Every route makes the authoritative state, the evidence gap, and the next permitted human step part of the main reading path.',
      items: [
        {
          number: '01',
          route: '/account-truth',
          surface: 'Account Truth',
          title: 'One account truth',
          body: 'Overview, Portfolio, Decision, and Operations always read the same saved account view.',
        },
        {
          number: '02',
          route: '/activity',
          surface: 'Activity history',
          title: 'Replayable evidence',
          body: 'Valuation time, activity scope, policy, and run record remain available on demand without crowding the main view.',
        },
        {
          number: '03',
          route: '/decision',
          surface: 'Decision gates',
          title: 'Controlled authority',
          body: 'Simulation and observation come first. Submission, recovery, and capital expansion always require a separate grant.',
        },
      ],
      action: 'Open surface',
    },
    principles: {
      eyebrow: 'Trust principles',
      title: 'Trust begins where convenience stops.',
      body: 'Karkinos treats accuracy, source transparency, repeatable evidence, and safe stopping as product qualities—not implementation details.',
      rows: [
        {
          label: 'Read behavior',
          value:
            'Opening a page reads saved evidence. It never refreshes data sources or changes account facts in the background.',
        },
        {
          label: 'Evidence references',
          value:
            'Human-readable state comes first; full evidence references remain copyable on demand.',
        },
        {
          label: 'Missing data',
          value:
            'Missing, stale, estimated, or unreconciled evidence stays visible and blocks authority.',
        },
        {
          label: 'Broker boundary',
          value:
            'Research and AI cannot place broker orders; manual review remains the default.',
        },
      ],
    },
    workflow: {
      eyebrow: 'Capability flow',
      title: 'From an idea to a controlled decision.',
      steps: [
        {
          number: '01',
          title: 'Research',
          body: 'Bind the idea to reproducible data, costs, and an explicit evaluation window.',
        },
        {
          number: '02',
          title: 'Validate',
          body: 'Check after-cost credibility, evidence completeness, and promotion eligibility.',
        },
        {
          number: '03',
          title: 'Review',
          body: 'Bring account facts, research, risk, simulation evidence, and human judgment together.',
        },
        {
          number: '04',
          title: 'Control',
          body: 'Expose only the authority that is explicitly granted, with a safe next step.',
        },
      ],
    },
    cta: {
      eyebrow: 'Personal capital deserves professional evidence',
      title: 'Inspect the evidence before the action.',
      body: 'The private workbench keeps account facts, blockers, and the currently permitted next step in one operational reading path.',
    },
    footer: {
      tagline:
        'An evidence-first personal quant investment workspace for the China market.',
      product: 'Product',
      resources: 'Resources',
      principles: 'Principles',
      overview: 'Workbench overview',
      evidence: 'Evidence model',
      workflow: 'Capability flow',
      docs: 'Project documentation',
      source: 'Source repository',
      persisted: 'Saved evidence',
      human: 'Human confirmation',
      closed: 'Stops on incomplete evidence',
      note: 'Research and controlled decision support. No default real-money automation.',
    },
  },
  zh: {
    skip: '跳到主内容',
    brandLabel: 'Karkinos 首页',
    navLabel: '公开导航',
    sectionNavLabel: '页面分区',
    nav: {
      product: '产品',
      principles: '可信原则',
      workflow: '工作流',
      docs: '文档',
    },
    enter: '进入私有工作台',
    enterShort: '工作台',
    language: '切换为英文',
    lightTheme: '切换为 Latte 浅色主题',
    darkTheme: '切换为 Mocha 深色主题',
    hero: {
      eyebrow: '中国市场 · 个人量化投资工作台',
      title: '让每一个投资决定，都有证据可回放。',
      body: 'Karkinos 把账户事实、研究、风控与人工复核连成一条可审计路径；证据先行，权限始终显式。',
      explore: '了解能力流程',
    },
    evidence: {
      eyebrow: '产品路径 · 不含账户数据',
      title: '证据向前，权限保持显式。',
      routeLabel: '公开页到私有工作台路径',
      publicRoute: '公开产品首页',
      privateRoute: '私有证据工作台',
      flowLabel: '决策证据路径',
      previewLabel: '工作台结构',
      caption: '仅展示产品结构，不包含任何账户、收益、订单或成交数据。',
      metrics: [
        { label: '账户事实', value: '保持一致', detail: '一份账户视图' },
        { label: '证据质量', value: '保持可见', detail: '新鲜度与缺口' },
        { label: '默认权限', value: '人工控制', detail: '仅查看与复核' },
      ],
      priority: {
        eyebrow: '操作优先级',
        title: '先处理最高优先级阻断。',
        reasonLabel: '原因',
        reason: '缺失或过期证据始终保持可见。',
        nextLabel: '安全下一步',
        next: '打开对应的证据界面。',
      },
      rows: [
        { label: '账户事实', detail: '同一账户视图', state: '已保存' },
        { label: '研究结论', detail: '数据与结论关联', state: '可追溯' },
        { label: '风控门禁', detail: '阈值与原因', state: '已评估' },
        { label: '人工复核', detail: '权限始终明确', state: '必须' },
      ],
      outcomeLabel: '默认权限',
      outcome: '仅查看与复核',
      outcomeNote: '默认不允许下单、撤单、自动恢复或资本扩容。',
    },
    proof: {
      eyebrow: '产品证明',
      title: '看见事实，也看见边界。',
      body: '每个界面都把权威状态、证据缺口和当前允许的人工下一步放在主阅读路径中。',
      items: [
        {
          number: '01',
          route: '/account-truth',
          surface: '账户事实',
          title: '唯一账户事实',
          body: '首页、组合、决策和运营始终读取同一份已保存账户视图。',
        },
        {
          number: '02',
          route: '/activity',
          surface: '交易流水',
          title: '证据可重放',
          body: '估值时间、流水范围、规则和运行记录按需可查，不占用主阅读路径。',
        },
        {
          number: '03',
          route: '/decision',
          surface: '决策门禁',
          title: '权限受控',
          body: '先模拟、再观察；提交、恢复与资本扩容始终需要单独授权。',
        },
      ],
      action: '查看界面',
    },
    principles: {
      eyebrow: '可信原则',
      title: '可信，不靠隐藏不确定性。',
      body: 'Karkinos 把准确性、来源透明、证据可复查和证据不足时安全停下视为产品品质。',
      rows: [
        {
          label: '读取行为',
          value:
            '打开页面只读取已保存证据；不会在后台刷新数据源或改写账户事实。',
        },
        {
          label: '证据明细',
          value: '先显示人能理解的状态，完整证据标识在需要时仍可复制。',
        },
        {
          label: '缺失数据',
          value: '缺失、过期、估计或未对账证据保持可见，并阻断权威结论。',
        },
        {
          label: '券商边界',
          value: '研究与 AI 不能向券商下单，人工复核始终是默认路径。',
        },
      ],
    },
    workflow: {
      eyebrow: '能力流程',
      title: '从一个想法，到一次受控决策。',
      steps: [
        {
          number: '01',
          title: '研究',
          body: '将想法绑定到可复现数据、成本与明确的评估窗口。',
        },
        {
          number: '02',
          title: '验证',
          body: '检查费后可信度、证据完整性与策略推广资格。',
        },
        {
          number: '03',
          title: '复核',
          body: '聚合账户事实、研究、风控、模拟证据和人工判断。',
        },
        {
          number: '04',
          title: '受控',
          body: '只暴露被明确授予的权限，并给出安全下一步。',
        },
      ],
    },
    cta: {
      eyebrow: '个人资本，也值得专业证据',
      title: '先检查证据，再决定是否行动。',
      body: '私有工作台把账户事实、阻断原因和当前允许的安全下一步放在同一条操作路径中。',
    },
    footer: {
      tagline: '面向中国市场的证据优先个人量化投资工作台。',
      product: '产品',
      resources: '资源',
      principles: '原则',
      overview: '工作台首页',
      evidence: '证据模型',
      workflow: '能力流程',
      docs: '项目文档',
      source: '源码仓库',
      persisted: '已保存证据',
      human: '人工确认',
      closed: '证据不足即停止',
      note: '用于研究与受控决策支持，不默认启用真实资金自动化。',
    },
  },
} as const;

const docsUrl = 'https://github.com/imReese/Karkinos/tree/main/docs';
const sourceUrl = 'https://github.com/imReese/Karkinos';

type PublicHomePanel = 'home' | 'product' | 'principles' | 'workflow';

function initialPublicHomePanel(): PublicHomePanel {
  const panel = window.location.hash.slice(1);
  return panel === 'product' || panel === 'principles' || panel === 'workflow'
    ? panel
    : 'home';
}

export function PublicHomePage() {
  const { locale, setLocale, resolvedTheme, setTheme } = usePreferences();
  const copy = publicHomeCopy[locale];
  const nextTheme = resolvedTheme === 'dark' ? 'light' : 'dark';
  const [activePanel, setActivePanel] = useState<PublicHomePanel>(
    initialPublicHomePanel,
  );
  const handleLocalOverflowKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (
      (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') ||
      event.currentTarget.scrollWidth <= event.currentTarget.clientWidth
    ) {
      return;
    }
    event.preventDefault();
    const direction = event.key === 'ArrowRight' ? 1 : -1;
    event.currentTarget.scrollBy({
      left: direction * Math.max(240, event.currentTarget.clientWidth * 0.78),
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'auto'
        : 'smooth',
    });
  };

  useEffect(() => {
    const syncPanelWithHash = () => {
      const panel = initialPublicHomePanel();
      setActivePanel(panel);
      if (panel !== 'home') {
        window.requestAnimationFrame(() => {
          document.getElementById(panel)?.focus();
        });
      }
    };
    window.addEventListener('hashchange', syncPanelWithHash);
    if (window.location.hash) {
      syncPanelWithHash();
    }
    return () => window.removeEventListener('hashchange', syncPanelWithHash);
  }, []);

  return (
    <div className="app-public-home" data-active-panel={activePanel}>
      <a className="app-public-skip-link" href="#public-home-main">
        {copy.skip}
      </a>

      <header className="app-public-header">
        <div className="app-public-container app-public-header-inner">
          <Link
            to="/"
            className="app-public-brand"
            aria-label={copy.brandLabel}
            onClick={() => setActivePanel('home')}
          >
            <span
              className="app-brand-glyph app-public-brand-glyph"
              aria-hidden="true"
            >
              <KarkinosMark />
            </span>
            <span className="app-product-mark app-public-product-mark">
              Karkinos
            </span>
          </Link>

          <nav className="app-public-nav" aria-label={copy.navLabel}>
            <a
              href="#product"
              aria-current={activePanel === 'product' ? 'location' : undefined}
              onClick={() => setActivePanel('product')}
            >
              {copy.nav.product}
            </a>
            <a
              href="#principles"
              aria-current={
                activePanel === 'principles' ? 'location' : undefined
              }
              onClick={() => setActivePanel('principles')}
            >
              {copy.nav.principles}
            </a>
            <a
              href="#workflow"
              aria-current={activePanel === 'workflow' ? 'location' : undefined}
              onClick={() => setActivePanel('workflow')}
            >
              {copy.nav.workflow}
            </a>
            <a href={docsUrl} target="_blank" rel="noreferrer">
              {copy.nav.docs}
            </a>
          </nav>

          <div className="app-public-actions">
            <button
              type="button"
              className="app-public-icon-button"
              aria-label={copy.language}
              onClick={() => setLocale(locale === 'zh' ? 'en' : 'zh')}
            >
              <Languages aria-hidden="true" />
              <span aria-hidden="true">{locale === 'zh' ? 'EN' : '中'}</span>
            </button>
            <button
              type="button"
              className="app-public-icon-button app-public-theme-button"
              aria-label={
                nextTheme === 'light' ? copy.lightTheme : copy.darkTheme
              }
              onClick={() => setTheme(nextTheme)}
            >
              {nextTheme === 'light' ? (
                <Sun aria-hidden="true" />
              ) : (
                <Moon aria-hidden="true" />
              )}
            </button>
            <Link
              to="/overview"
              className="app-button-primary app-public-header-cta"
              aria-label={copy.enter}
            >
              <span className="app-public-header-cta-long">{copy.enter}</span>
              <span className="app-public-header-cta-short" aria-hidden="true">
                {copy.enterShort}
              </span>
              <ArrowRight aria-hidden="true" />
            </Link>
          </div>
        </div>
      </header>

      <main className="app-public-main" id="public-home-main">
        <section
          className="app-public-container app-public-hero app-public-panel"
          data-active={activePanel === 'home'}
          data-public-panel="home"
        >
          <div className="app-public-hero-copy">
            <p className="app-kicker app-public-eyebrow">{copy.hero.eyebrow}</p>
            <h1 className="app-public-hero-title">
              {locale === 'zh' ? (
                <>
                  让每一个
                  <span className="app-public-title-phrase">投资决定</span>，
                  <span className="app-public-title-phrase">都有</span>
                  证据可回放。
                </>
              ) : (
                copy.hero.title
              )}
            </h1>
            <p className="app-public-hero-body">{copy.hero.body}</p>
            <div className="app-public-hero-actions">
              <Link
                to="/overview"
                className="app-button-primary app-public-primary-cta"
              >
                <span>{copy.enter}</span>
                <ArrowRight aria-hidden="true" />
              </Link>
              <a
                className="app-public-text-link"
                href="#workflow"
                onClick={() => setActivePanel('workflow')}
              >
                {copy.hero.explore}
                <ArrowRight aria-hidden="true" />
              </a>
            </div>
          </div>

          <nav
            className="app-public-section-index"
            aria-label={copy.sectionNavLabel}
          >
            <a
              href="#product"
              aria-current={activePanel === 'product' ? 'location' : undefined}
              onClick={() => setActivePanel('product')}
            >
              {copy.nav.product}
            </a>
            <a
              href="#principles"
              aria-current={
                activePanel === 'principles' ? 'location' : undefined
              }
              onClick={() => setActivePanel('principles')}
            >
              {copy.nav.principles}
            </a>
            <a
              href="#workflow"
              aria-current={activePanel === 'workflow' ? 'location' : undefined}
              onClick={() => setActivePanel('workflow')}
            >
              {copy.nav.workflow}
            </a>
          </nav>

          <figure
            className="app-public-evidence-frame"
            data-testid="public-evidence-trace"
          >
            <div
              className="app-public-route-identity"
              aria-label={copy.evidence.routeLabel}
            >
              <span>
                <small>{copy.evidence.publicRoute}</small>
                <code>/</code>
              </span>
              <ArrowRight aria-hidden="true" />
              <span>
                <small>{copy.evidence.privateRoute}</small>
                <code>/overview</code>
              </span>
            </div>
            <div className="app-public-evidence-heading">
              <div>
                <p className="app-kicker app-public-eyebrow">
                  {copy.evidence.eyebrow}
                </p>
                <h2>{copy.evidence.title}</h2>
              </div>
              <ShieldCheck aria-hidden="true" />
            </div>
            <dl
              className="app-public-preview-metrics"
              aria-label={copy.evidence.previewLabel}
            >
              {copy.evidence.metrics.map((metric) => (
                <div key={metric.label}>
                  <dt>{metric.label}</dt>
                  <dd>{metric.value}</dd>
                  <small>{metric.detail}</small>
                </div>
              ))}
            </dl>
            <div className="app-public-preview-workspace">
              <section
                className="app-public-priority-preview"
                aria-labelledby="public-priority-title"
              >
                <p className="app-kicker app-public-eyebrow">
                  {copy.evidence.priority.eyebrow}
                </p>
                <h3 id="public-priority-title">
                  {copy.evidence.priority.title}
                </h3>
                <dl>
                  <div>
                    <dt>{copy.evidence.priority.reasonLabel}</dt>
                    <dd>{copy.evidence.priority.reason}</dd>
                  </div>
                  <div>
                    <dt>{copy.evidence.priority.nextLabel}</dt>
                    <dd>{copy.evidence.priority.next}</dd>
                  </div>
                </dl>
              </section>
              <ol
                className="app-public-evidence-flow"
                aria-label={copy.evidence.flowLabel}
              >
                {copy.evidence.rows.map((row, index) => (
                  <li className="app-public-evidence-step" key={row.label}>
                    <span className="app-public-evidence-index">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <span
                      className="app-public-evidence-node"
                      aria-hidden="true"
                    />
                    <span className="app-public-evidence-copy">
                      <strong>{row.label}</strong>
                      <small>{row.detail}</small>
                    </span>
                    <span className="app-public-evidence-state">
                      {row.state}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
            <div className="app-public-evidence-boundary">
              <LockKeyhole aria-hidden="true" />
              <span>
                <small>{copy.evidence.outcomeLabel}</small>
                <strong>{copy.evidence.outcome}</strong>
                <span>{copy.evidence.outcomeNote}</span>
              </span>
            </div>
            <figcaption>{copy.evidence.caption}</figcaption>
          </figure>
        </section>

        <section
          id="product"
          className="app-public-container app-public-section app-public-panel"
          data-active={activePanel === 'product'}
          data-public-panel="product"
          aria-labelledby="public-product-title"
          tabIndex={-1}
        >
          <div className="app-public-section-heading">
            <p className="app-kicker app-public-eyebrow">
              {copy.proof.eyebrow}
            </p>
            <h2 id="public-product-title">{copy.proof.title}</h2>
            <p>{copy.proof.body}</p>
          </div>
          <div
            className="app-public-proof-grid"
            role="list"
            aria-label={copy.proof.eyebrow}
            data-local-overflow="public-product-proof"
            tabIndex={0}
            onKeyDown={handleLocalOverflowKeyDown}
          >
            {copy.proof.items.map((item) => (
              <article key={item.number} role="listitem">
                <div className="app-public-proof-route">
                  <span>{item.number}</span>
                  <code>{item.route}</code>
                </div>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
                <Link to={item.route} className="app-public-proof-link">
                  <span>
                    {copy.proof.action}: {item.surface}
                  </span>
                  <ArrowRight aria-hidden="true" />
                </Link>
              </article>
            ))}
          </div>
        </section>

        <section
          id="principles"
          className="app-public-container app-public-section app-public-principles app-public-panel"
          data-active={activePanel === 'principles'}
          data-public-panel="principles"
          aria-labelledby="public-principles-title"
          tabIndex={-1}
        >
          <div className="app-public-section-heading app-public-principles-heading">
            <p className="app-kicker app-public-eyebrow">
              {copy.principles.eyebrow}
            </p>
            <h2 id="public-principles-title">{copy.principles.title}</h2>
            <p>{copy.principles.body}</p>
          </div>
          <dl
            className="app-public-principle-list"
            aria-label={copy.principles.eyebrow}
            data-local-overflow="public-principles"
            tabIndex={0}
            onKeyDown={handleLocalOverflowKeyDown}
          >
            {copy.principles.rows.map((row, index) => (
              <div key={row.label}>
                <dt>
                  <span>{String(index + 1).padStart(2, '0')}</span>
                  {row.label}
                </dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <div
          className="app-public-workflow-panel app-public-panel"
          data-active={activePanel === 'workflow'}
          data-public-panel="workflow"
        >
          <section
            id="workflow"
            className="app-public-container app-public-section"
            aria-labelledby="public-workflow-title"
            tabIndex={-1}
          >
            <div className="app-public-section-heading">
              <p className="app-kicker app-public-eyebrow">
                {copy.workflow.eyebrow}
              </p>
              <h2 id="public-workflow-title">{copy.workflow.title}</h2>
            </div>
            <ol
              className="app-public-workflow"
              aria-label={copy.workflow.eyebrow}
              data-local-overflow="public-workflow"
              tabIndex={0}
              onKeyDown={handleLocalOverflowKeyDown}
            >
              {copy.workflow.steps.map((step) => (
                <li key={step.number}>
                  <span>{step.number}</span>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </li>
              ))}
            </ol>
          </section>

          <section className="app-public-container app-public-cta-section">
            <div>
              <p className="app-kicker app-public-eyebrow">
                {copy.cta.eyebrow}
              </p>
              <h2>{copy.cta.title}</h2>
              <p>{copy.cta.body}</p>
            </div>
            <Link
              to="/overview"
              className="app-button-primary app-public-primary-cta"
            >
              <span>{copy.enter}</span>
              <ArrowRight aria-hidden="true" />
            </Link>
          </section>
        </div>
      </main>

      <footer className="app-public-footer">
        <div className="app-public-container app-public-footer-grid">
          <div className="app-public-footer-brand">
            <div className="app-public-brand">
              <span
                className="app-brand-glyph app-public-brand-glyph"
                aria-hidden="true"
              >
                <KarkinosMark />
              </span>
              <span className="app-product-mark app-public-product-mark">
                Karkinos
              </span>
            </div>
            <p>{copy.footer.tagline}</p>
          </div>
          <div>
            <h2>{copy.footer.product}</h2>
            <Link to="/overview">{copy.footer.overview}</Link>
            <a href="#principles" onClick={() => setActivePanel('principles')}>
              {copy.footer.evidence}
            </a>
            <a href="#workflow" onClick={() => setActivePanel('workflow')}>
              {copy.footer.workflow}
            </a>
          </div>
          <div>
            <h2>{copy.footer.resources}</h2>
            <a href={docsUrl} target="_blank" rel="noreferrer">
              {copy.footer.docs}
            </a>
            <a href={sourceUrl} target="_blank" rel="noreferrer">
              {copy.footer.source}
            </a>
          </div>
          <div>
            <h2>{copy.footer.principles}</h2>
            <span>{copy.footer.persisted}</span>
            <span>{copy.footer.human}</span>
            <span>{copy.footer.closed}</span>
          </div>
        </div>
        <div className="app-public-container app-public-footer-note">
          <span>Karkinos</span>
          <span>{copy.footer.note}</span>
          <span className="app-public-footer-links">
            <a href={docsUrl} target="_blank" rel="noreferrer">
              {copy.footer.docs}
            </a>
            <a href={sourceUrl} target="_blank" rel="noreferrer">
              {copy.footer.source}
            </a>
          </span>
        </div>
      </footer>
    </div>
  );
}
