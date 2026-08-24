import type { ReactNode } from 'react';

import { AppShellMobileNavigation } from './app-shell-mobile-navigation';
import { AppShellSidebar } from './app-shell-sidebar';
import { AppShellToolbar } from './app-shell-toolbar';
import { useAppShellController } from './use-app-shell-controller';
import { WorkspaceCommandMenu } from './workspace-command-menu';

export function AppShell({ children }: { children: ReactNode }) {
  const shell = useAppShellController();

  return (
    <div className="app-root min-h-[100dvh] w-full">
      <div className="app-shell-frame flex h-[100dvh] min-h-[100dvh] w-full min-w-0">
        <div
          className={`app-mobile-navigation-backdrop fixed inset-0 z-[90] bg-[color-mix(in_srgb,var(--app-bg)_72%,transparent)] xl:hidden ${
            shell.mobileNavOpen
              ? 'opacity-100'
              : 'pointer-events-none opacity-0'
          }`}
          data-mobile-open={shell.mobileNavOpen}
          data-testid="mobile-navigation-backdrop"
          aria-hidden={!shell.mobileNavOpen}
          onClick={shell.closeMobileNav}
        />

        <AppShellSidebar
          copy={shell.copy}
          desktopNavExpanded={shell.desktopNavExpanded}
          locale={shell.locale}
          mobileNavCloseRef={shell.mobileNavCloseRef}
          mobileNavOpen={shell.mobileNavOpen}
          mobileNavRef={shell.mobileNavRef}
          onDesktopToggle={shell.toggleDesktopNav}
          onMobileNavClose={shell.closeMobileNav}
          pathname={shell.pathname}
        />

        <main className="app-shell-main relative flex min-w-0 flex-1 flex-col">
          <AppShellToolbar
            commandOpen={shell.commandOpen}
            copy={shell.copy}
            locale={shell.locale}
            mobileNavOpen={shell.mobileNavOpen}
            onCommandOpen={shell.openCommand}
            onLocaleChange={shell.setLocale}
            onMobileNavToggle={shell.toggleMobileNav}
            onThemeChange={shell.setTheme}
            status={shell.status}
            theme={shell.theme}
          />

          <WorkspaceCommandMenu
            copy={shell.copy}
            open={shell.commandOpen}
            locale={shell.locale}
            onClose={shell.closeCommand}
            pathname={shell.pathname}
          />

          <div
            ref={shell.contentRef}
            className="app-shell-content min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto [contain:layout_paint]"
          >
            <div className="w-full min-w-0 px-3 py-3 sm:px-4 sm:py-4 lg:px-5 lg:py-5 xl:px-6">
              <div className="app-route-stage" key={shell.pathname}>
                {children}
              </div>
            </div>
          </div>

          <AppShellMobileNavigation
            copy={shell.copy}
            mobileNavOpen={shell.mobileNavOpen}
            onMobileNavClose={shell.closeMobileNav}
            onMobileNavToggle={shell.toggleMobileNav}
            pathname={shell.pathname}
          />
        </main>
      </div>
    </div>
  );
}
