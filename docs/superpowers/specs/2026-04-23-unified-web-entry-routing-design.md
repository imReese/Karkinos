# Unified Web Entry Routing Design

## Context

MyQuant currently has a FastAPI backend and a React frontend using TanStack Router.
The backend exposes resource APIs under `/api/*` and mounts `web/dist` at `/` when a production frontend build exists.
The frontend defines customer-facing routes such as `/portfolio`, `/activity`, `/risk`, `/market`, and `/settings`.

The product goal is to match mature web product behavior: one stable customer entry point, direct links that can be refreshed or shared, and a clear separation between page routes and data APIs.

## Decision

Use `http://localhost:8000` as the product entry point for customer demos and production-like use.
Use `http://localhost:5173` only as a developer hot-reload endpoint.

The backend remains the owner of deployment entry routing:

- `/api/*` is reserved for JSON APIs.
- `/ws` is reserved for realtime WebSocket traffic.
- Static assets such as `/assets/index-*.js` and `/assets/index-*.css` are served from `web/dist`.
- Customer page paths such as `/portfolio`, `/activity`, `/risk`, `/market`, and `/settings` return the React app shell.
- Unknown extensionless page paths return the app shell so the frontend router can show a not-found or fallback state.
- Missing asset paths with file extensions remain real 404s.

The frontend remains the owner of page composition and client-side navigation.
Each page fetches the resource APIs it needs; APIs are not forced into a one-page-one-endpoint shape.

## Goals

- Refreshing a customer page on `localhost:8000` keeps the user on the same URL and page.
- Directly opening a customer page URL works without first visiting `/`.
- Browser back/forward navigation works through real URLs, not hidden in-memory page state.
- Query state that affects the visible page, such as portfolio filters, remains encoded in the URL when practical.
- Development scripts make it clear which URL is the product entry and which URL is the hot-reload entry.
- Tests cover the backend SPA fallback contract for all current page routes.

## Non-Goals

- Do not migrate to Next.js, Remix, or server-side rendering.
- Do not add a backend page API for every frontend page.
- Do not introduce CDN, API gateway, or multi-service deployment complexity.
- Do not change business API response shapes unless a routing bug requires it.
- Do not make `5173` the customer-facing product URL.

## Architecture

The deployed request flow is:

1. Browser requests `GET /portfolio`.
2. FastAPI routing does not match `/api/*` or `/ws`, then static handling serves `web/dist/index.html`.
3. React boots and TanStack Router matches `/portfolio`.
4. The page fetches resource APIs such as `/api/portfolio`, `/api/portfolio/live-holdings`, and `/api/portfolio/overview`.

The development flow is:

1. `./scripts/start_server.sh dev` starts the backend on `8000` and Vite on `5173`.
2. The backend on `8000` is the product-like entry when `web/dist` exists.
3. Vite on `5173` remains available for frontend hot reload.
4. Script output and documentation explicitly label the two URLs to avoid treating them as equivalent customer entrances.

## Route Contract

Backend route classes:

- API routes: paths beginning with `/api/` must be handled by FastAPI routers and return JSON responses or API errors.
- WebSocket route: `/ws` must not be swallowed by static fallback.
- Static asset routes: extension paths must return the asset if present and 404 if missing.
- Page routes: extensionless paths outside `/api` and `/ws` must return `index.html`.

Current first-class page routes:

- `/`
- `/portfolio`
- `/activity`
- `/risk`
- `/market`
- `/settings`

Current resource API groups:

- `/api/portfolio/*`
- `/api/market/*`
- `/api/ledger/*`
- `/api/signals/*`
- `/api/backtest/*`
- `/api/settings/*`

## Error Handling

If `web/dist` is missing, the backend should continue serving APIs and should not pretend the product UI is available.
The startup or script output should tell the operator that a frontend build is required for the `8000` product entry.

If a page route is requested and `index.html` exists, the backend returns the app shell.
The frontend router is responsible for any unknown page message.

If an API route fails, the response remains an API error and must not fallback to `index.html`.

## Testing

Backend tests should verify:

- `GET /portfolio`, `/activity`, `/risk`, `/market`, and `/settings` return the same `index.html` app shell when `web/dist` exists.
- `GET /api/...` is not handled by SPA fallback.
- Missing extension assets such as `/missing.js` return 404.
- The existing API route behavior is unchanged.

Frontend tests should verify:

- Navigation links point to stable page URLs.
- Portfolio search/filter state remains represented in URL search parameters.

Manual verification should include:

- Build the frontend.
- Start the backend product entry.
- Open each customer page directly on `http://localhost:8000`.
- Refresh each page and confirm the URL and visible page are preserved.

## Rollout

Implement this as a focused routing and developer-experience change:

- Tighten or extend the backend SPA fallback tests.
- Adjust backend static fallback only if the tests reveal a gap.
- Update startup script output and documentation to label `8000` as the product entry and `5173` as the hot-reload entry.
- Keep resource APIs as they are unless tests expose a concrete routing conflict.

## Acceptance Criteria

- `http://localhost:8000/portfolio` opens the portfolio page directly.
- Refreshing `http://localhost:8000/portfolio` stays on the portfolio page.
- The same behavior works for `/activity`, `/risk`, `/market`, and `/settings`.
- `/api/*` continues to return API responses, not HTML.
- Missing static assets still return 404.
- Documentation explains the difference between the product entry and the Vite development entry.
