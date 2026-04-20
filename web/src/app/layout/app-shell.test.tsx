import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import { AppShell } from "./app-shell";
import { PreferencesProvider } from "../preferences";

function renderShell() {
  window.scrollTo = () => {};
  window.localStorage.clear();
  const matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("light"),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: matchMedia,
  });

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
}

test("renders portfolio workspace navigation", async () => {
  renderShell();

  expect(await screen.findByText("Overview")).toBeTruthy();
  expect(await screen.findByText("Portfolio")).toBeTruthy();
  expect(await screen.findByText("Activity")).toBeTruthy();
  expect(await screen.findByText("Overview page")).toBeTruthy();
});

test("switches interface language from english to chinese", async () => {
  renderShell();
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "中文" }));

  expect(await screen.findByText("总览")).toBeTruthy();
  expect(await screen.findByText("组合")).toBeTruthy();
  expect(await screen.findByText("流水")).toBeTruthy();
  expect(window.localStorage.getItem("myquant.locale")).toBe("zh");
});

test("switches theme preference and persists it", async () => {
  renderShell();
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Dark" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(window.localStorage.getItem("myquant.theme")).toBe("dark");

  await user.click(await screen.findByRole("button", { name: "Light" }));
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(window.localStorage.getItem("myquant.theme")).toBe("light");
});
