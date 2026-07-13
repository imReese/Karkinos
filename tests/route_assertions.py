from __future__ import annotations

from typing import Any


def registered_app_routes(app: Any) -> tuple[Any, ...]:
    """Return leaf routes across both flat and nested FastAPI registrations."""

    pending = list(app.routes)
    routes: list[Any] = []
    while pending:
        route = pending.pop(0)
        original_router = getattr(route, "original_router", None)
        nested_routes = getattr(original_router, "routes", None)
        if nested_routes is not None:
            pending[0:0] = nested_routes
            continue
        routes.append(route)
    return tuple(routes)
