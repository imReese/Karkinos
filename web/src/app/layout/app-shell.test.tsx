import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import { AppShell } from "./app-shell";
import { PreferencesProvider } from "../preferences";

type MatchMediaMock = {
  setDarkMode: (matches: boolean) => void;
};

function installMatchMediaMock(initialDark = false): MatchMediaMock {
  let darkMode = initialDark;
  const listeners = new Set<(event: MediaQueryListEvent) => void>();

  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("prefers-color-scheme: dark") ? darkMode : !darkMode,
      media: query,
      onchange: null,
      addEventListener: vi.fn((event: string, listener: (event: MediaQueryListEvent) => void) => {
        if (event === "change") {
          listeners.add(listener);
        }
      }),
      removeEventListener: vi.fn(
        (event: string, listener: (event: MediaQueryListEvent) => void) => {
          if (event === "change") {
            listeners.delete(listener);
          }
        },
      ),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  return {
    setDarkMode(matches: boolean) {
      darkMode = matches;
      const event = {
        matches,
        media: "(prefers-color-scheme: dark)",
      } as MediaQueryListEvent;
      listeners.forEach((listener) => listener(event));
    },
  };
}

function renderShell() {
  window.scrollTo = () => {};
  window.localStorage.clear();
  const matchMedia = installMatchMediaMock();

  const rootRoute = createRootRoute({
    component: () => (
      <AppShell>
        <Outlet />
      </AppShell>
    ),
  });

  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => <div>Overview page</div>,
  });

  const routeTree = rootRoute.addChildren([indexRoute]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  const queryClient = new QueryClient();

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { matchMedia };
}

test("renders portfolio workspace navigation", async () => {
  renderShell();

  expect(await screen.findByText("Overview")).toBeTruthy();
  expect(await screen.findByText("Portfolio")).toBeTruthy();
  expect(await screen.findByText("Activity")).toBeTruthy();
  expect(await screen.findByText("Risk")).toBeTruthy();
  expect(await screen.findByText("Overview page")).toBeTruthy();
  expect(await screen.findByText("Workspace toolbar")).toBeTruthy();
  expect(await screen.findByLabelText("Account Status")).toBeTruthy();
});

test("switches interface language from english to chinese", async () => {
  renderShell();
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Language" }));
  await user.click(await screen.findByRole("menuitemradio", { name: "ZH" }));

  expect(await screen.findByText("总览")).toBeTruthy();
  expect(await screen.findByText("组合")).toBeTruthy();
  expect(await screen.findByText("流水")).toBeTruthy();
  expect(await screen.findByText("风险")).toBeTruthy();
  expect(await screen.findByText("全局工具栏")).toBeTruthy();
  expect(window.localStorage.getItem("myquant.locale")).toBe("zh");
});

test("switches theme preference and persists it", async () => {
  const { matchMedia } = renderShell();
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Dark theme" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(window.localStorage.getItem("myquant.theme")).toBe("dark");

  await user.click(await screen.findByRole("button", { name: "Light theme" }));
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(window.localStorage.getItem("myquant.theme")).toBe("light");

  act(() => {
    matchMedia.setDarkMode(true);
  });
  expect(document.documentElement.dataset.theme).toBe("light");

  await user.click(await screen.findByRole("button", { name: "System theme" }));
  expect(window.localStorage.getItem("myquant.theme")).toBeNull();
  expect(document.documentElement.dataset.theme).toBe("dark");

  act(() => {
    matchMedia.setDarkMode(false);
  });
  expect(document.documentElement.dataset.theme).toBe("light");
});

test("toggles mobile navigation from the global toolbar", async () => {
  renderShell();
  const user = userEvent.setup();

  const openButton = await screen.findByRole("button", { name: "Open navigation" });
  expect(openButton.getAttribute("aria-expanded")).toBe("false");

  await user.click(openButton);

  expect(
    (await screen.findAllByRole("button", { name: "Close navigation" })).length,
  ).toBeGreaterThan(0);
  expect(openButton.getAttribute("aria-expanded")).toBe("true");
  expect(await screen.findByLabelText("Navigation")).toBeTruthy();
});
