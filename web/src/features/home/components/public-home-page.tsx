import { ArrowRight, Languages, Moon, ShieldCheck, Sun } from 'lucide-react';
import { Link } from '@tanstack/react-router';

import { usePreferences } from '../../../app/preferences';

const publicHomeCopy = {
  en: {
    skip: 'Skip to main content',
    brandLabel: 'Karkinos home',
    navLabel: 'Public navigation',
    nav: {
      product: 'Product',
      principles: 'Trust',
      workflow: 'Workflow',
      docs: 'Docs',
    },
    enter: 'Enter workbench',
    language: 'Switch to Chinese',
    lightTheme: 'Switch to Latte theme',
    darkTheme: 'Switch to Mocha theme',
    hero: {
      eyebrow: 'China market · Personal quant workspace',
      title: 'Every decision should leave evidence.',
      body: 'Karkinos connects persisted account facts, research, risk gates, paper and shadow rehearsal, and human review into one auditable path—from research to controlled execution.',
      explore: 'Explore the workflow',
      guardrails: [
        'Persisted facts, never an invisible refresh',
        'Missing evidence fails closed',
        'Live-like actions remain human confirmed',
      ],
    },
    evidence: {
      eyebrow: 'Concept map · No account data',
      title: 'One decision. Four evidence layers.',
      caption:
        'A structural view of the product contract. It contains no account, return, order, or execution data.',
      rows: [
        { label: 'Account truth', value: 'Persisted projection' },
        { label: 'Research', value: 'Dataset bound' },
        { label: 'Risk', value: 'Gate evaluated' },
        { label: 'Authority', value: 'Human confirmed' },
      ],
    },
    proof: {
      eyebrow: 'Product proof',
      title: 'Proof is a product surface—not a footnote.',
      body: 'The interface is organized around what is known, what is missing, what is blocked, and what a person can safely do next.',
      items: [
        {
          number: '01',
          title: 'One account truth',
          body: 'Overview, Portfolio, Decision, and Operations project the same canonical persisted facts.',
        },
        {
          number: '02',
          title: 'Replayable evidence',
          body: 'Snapshot, ledger cutoff, policy, and run identity remain available without dominating the reading path.',
        },
        {
          number: '03',
          title: 'Controlled authority',
          body: 'Paper and shadow come first. Submission, recovery, and capital expansion are not ambient permissions.',
        },
      ],
    },
    principles: {
      eyebrow: 'Trust principles',
      title: 'Trust begins where convenience stops.',
      body: 'Karkinos treats accuracy, provenance, deterministic replay, and fail-closed behavior as product qualities—not backend trivia.',
      rows: [
        {
          label: 'Read behavior',
          value:
            'GET reads persisted projections; it does not contact providers or refresh facts.',
        },
        {
          label: 'Evidence identity',
          value:
            'Human-readable state first; technical fingerprints remain copyable on demand.',
        },
        {
          label: 'Missing data',
          value:
            'Missing, stale, estimated, or unreconciled evidence stays visible and blocks authority.',
        },
        {
          label: 'Broker boundary',
          value:
            'Strategies and AI never receive direct broker authority; manual review remains the default.',
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
          body: 'Bring account facts, research, risk, paper or shadow, and human judgment together.',
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
      title: 'See the workbench built around facts.',
      body: 'Enter the private workspace to inspect account truth, holdings, priorities, research, risk, and operations.',
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
      persisted: 'Persisted truth',
      human: 'Human confirmation',
      closed: 'Fail closed',
      note: 'Research and controlled decision support. No default real-money automation.',
    },
  },
  zh: {
    skip: '跳到主内容',
    brandLabel: 'Karkinos 首页',
    navLabel: '公开导航',
    nav: {
      product: '产品',
      principles: '可信原则',
      workflow: '工作流',
      docs: '文档',
    },
    enter: '进入工作台',
    language: '切换为英文',
    lightTheme: '切换为 Latte 浅色主题',
    darkTheme: '切换为 Mocha 深色主题',
    hero: {
      eyebrow: '中国市场 · 个人量化投资工作台',
      title: '让每一个投资决定，都有证据可回放。',
      body: 'Karkinos 将持久化账户事实、研究、风控门禁、paper/shadow 演练与人工复核连成可审计的路径，从研究走向受控执行。',
      explore: '了解能力流程',
      guardrails: [
        '只读取持久化事实，不做隐式刷新',
        '证据缺失时 fail closed',
        '类实盘动作始终需要人工确认',
      ],
    },
    evidence: {
      eyebrow: '结构示意 · 不含账户数据',
      title: '一次决策，四层证据。',
      caption: '这是产品契约的概念图，不包含任何账户、收益、订单或成交数据。',
      rows: [
        { label: '账户事实', value: '持久化投影' },
        { label: '研究结论', value: '绑定数据集' },
        { label: '风控门禁', value: '显式评估' },
        { label: '执行权限', value: '人工确认' },
      ],
    },
    proof: {
      eyebrow: '产品证明',
      title: '证据是产品界面，不是页脚附注。',
      body: '界面围绕“已知什么、缺少什么、什么被阻断、下一步可以安全做什么”来组织。',
      items: [
        {
          number: '01',
          title: '唯一账户事实',
          body: '首页、组合、决策和运营只投影同一份 canonical persisted facts。',
        },
        {
          number: '02',
          title: '证据可重放',
          body: 'snapshot、ledger cutoff、policy 与 run identity 完整保留，但不抢占主阅读路径。',
        },
        {
          number: '03',
          title: '权限受控',
          body: '从 paper/shadow 开始；submit、恢复与资本扩容从不是环境默认权限。',
        },
      ],
    },
    principles: {
      eyebrow: '可信原则',
      title: '可信，从拒绝便利的假象开始。',
      body: 'Karkinos 把准确性、数据来源、确定性重放和 fail-closed 行为视为产品品质，而非后端细节。',
      rows: [
        {
          label: '读取行为',
          value: 'GET 只读持久化投影，不联系 provider，不隐式刷新事实。',
        },
        {
          label: '证据身份',
          value: '先显示人能理解的状态，技术指纹在需要时仍可复制。',
        },
        {
          label: '缺失数据',
          value: '缺失、过期、估计或未对账证据保持可见，并阻断权威结论。',
        },
        {
          label: '券商边界',
          value: '策略与 AI 不获得直连券商权限，人工复核始终是默认。',
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
          body: '聚合账户事实、研究、风控、paper/shadow 和人工判断。',
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
      title: '进入一个围绕事实建立的工作台。',
      body: '在私有工作台中查看账户事实、当前持仓、优先任务、研究、风险与运营。',
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
      persisted: '持久化事实',
      human: '人工确认',
      closed: 'Fail closed',
      note: '用于研究与受控决策支持，不默认启用真实资金自动化。',
    },
  },
} as const;

const docsUrl = 'https://github.com/imReese/Karkinos/tree/main/docs';
const sourceUrl = 'https://github.com/imReese/Karkinos';

export function PublicHomePage() {
  const { locale, setLocale, resolvedTheme, setTheme } = usePreferences();
  const copy = publicHomeCopy[locale];
  const nextTheme = resolvedTheme === 'dark' ? 'light' : 'dark';

  return (
    <div className="app-public-home">
      <a className="app-public-skip-link" href="#public-home-main">
        {copy.skip}
      </a>

      <header className="app-public-header">
        <div className="app-public-container app-public-header-inner">
          <Link
            to="/"
            className="app-public-brand"
            aria-label={copy.brandLabel}
          >
            <span
              className="app-brand-glyph app-public-brand-glyph"
              aria-hidden="true"
            >
              K
            </span>
            <span className="app-product-mark app-public-product-mark">
              Karkinos
            </span>
          </Link>

          <nav className="app-public-nav" aria-label={copy.navLabel}>
            <a href="#product">{copy.nav.product}</a>
            <a href="#principles">{copy.nav.principles}</a>
            <a href="#workflow">{copy.nav.workflow}</a>
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
            >
              <span>{copy.enter}</span>
              <ArrowRight aria-hidden="true" />
            </Link>
          </div>
        </div>
      </header>

      <main id="public-home-main">
        <section className="app-public-container app-public-hero">
          <div className="app-public-hero-copy">
            <p className="app-kicker app-public-eyebrow">{copy.hero.eyebrow}</p>
            <h1 className="app-public-hero-title">{copy.hero.title}</h1>
            <p className="app-public-hero-body">{copy.hero.body}</p>
            <div className="app-public-hero-actions">
              <Link
                to="/overview"
                className="app-button-primary app-public-primary-cta"
              >
                <span>{copy.enter}</span>
                <ArrowRight aria-hidden="true" />
              </Link>
              <a className="app-public-text-link" href="#workflow">
                {copy.hero.explore}
                <ArrowRight aria-hidden="true" />
              </a>
            </div>
            <ul
              className="app-public-guardrails"
              aria-label={copy.principles.title}
            >
              {copy.hero.guardrails.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>

          <figure className="app-public-evidence-frame">
            <div className="app-public-evidence-heading">
              <div>
                <p className="app-kicker app-public-eyebrow">
                  {copy.evidence.eyebrow}
                </p>
                <h2>{copy.evidence.title}</h2>
              </div>
              <ShieldCheck aria-hidden="true" />
            </div>
            <div className="app-public-evidence-rows">
              {copy.evidence.rows.map((row, index) => (
                <div className="app-public-evidence-row" key={row.label}>
                  <span className="app-public-evidence-index">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span>{row.label}</span>
                  <strong>{row.value}</strong>
                </div>
              ))}
            </div>
            <figcaption>{copy.evidence.caption}</figcaption>
          </figure>
        </section>

        <section
          id="product"
          className="app-public-container app-public-section"
        >
          <div className="app-public-section-heading">
            <p className="app-kicker app-public-eyebrow">
              {copy.proof.eyebrow}
            </p>
            <h2>{copy.proof.title}</h2>
            <p>{copy.proof.body}</p>
          </div>
          <div className="app-public-proof-grid">
            {copy.proof.items.map((item) => (
              <article key={item.number}>
                <span>{item.number}</span>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section
          id="principles"
          className="app-public-container app-public-section app-public-principles"
        >
          <div className="app-public-section-heading app-public-principles-heading">
            <p className="app-kicker app-public-eyebrow">
              {copy.principles.eyebrow}
            </p>
            <h2>{copy.principles.title}</h2>
            <p>{copy.principles.body}</p>
          </div>
          <dl className="app-public-principle-list">
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

        <section
          id="workflow"
          className="app-public-container app-public-section"
        >
          <div className="app-public-section-heading">
            <p className="app-kicker app-public-eyebrow">
              {copy.workflow.eyebrow}
            </p>
            <h2>{copy.workflow.title}</h2>
          </div>
          <ol className="app-public-workflow">
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
            <p className="app-kicker app-public-eyebrow">{copy.cta.eyebrow}</p>
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
      </main>

      <footer className="app-public-footer">
        <div className="app-public-container app-public-footer-grid">
          <div className="app-public-footer-brand">
            <div className="app-public-brand">
              <span
                className="app-brand-glyph app-public-brand-glyph"
                aria-hidden="true"
              >
                K
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
            <a href="#principles">{copy.footer.evidence}</a>
            <a href="#workflow">{copy.footer.workflow}</a>
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
        </div>
      </footer>
    </div>
  );
}
