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

import { KarkinosMark } from '../../../shared/ui/brand/karkinos-mark';
import { usePreferences } from '../../../shared/preferences/context';
import { publicHomeCopy } from './public-home-copy';
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
