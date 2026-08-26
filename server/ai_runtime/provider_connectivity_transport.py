"""Bounded HTTPS transports for OpenAI-compatible provider edges."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

import httpx

from .contracts import canonical_json
from .provider_connectivity_contracts import HttpJsonResponse, ProviderProbeError


class UrllibJsonTransport:
    """Small dependency-free HTTPS transport with sanitized failure codes."""

    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> HttpJsonResponse:
        request = Request(
            url,
            data=canonical_json(payload).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        try:
            with build_opener(NoRedirectHandler()).open(
                request,
                timeout=timeout_seconds,
            ) as response:  # noqa: S310
                body = response.read(1_048_576)
                status_code = int(response.status)
        except HTTPError as exc:
            body = exc.read(1_048_576)
            status_code = int(exc.code)
        except TimeoutError as exc:
            raise ProviderProbeError("provider_timeout") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            code = (
                "provider_timeout"
                if isinstance(reason, TimeoutError)
                else "network_error"
            )
            raise ProviderProbeError(code) from exc
        try:
            decoded: object = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = None
        return HttpJsonResponse(status_code=status_code, payload=decoded)


class HttpxDeadlineJsonTransport:
    """HTTPS JSON transport with a real end-to-end wall-clock deadline."""

    _MAX_RESPONSE_BYTES = 1_048_576

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._transport = transport

    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> HttpJsonResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise ProviderProbeError("provider_transport_requires_worker_thread")
        return asyncio.run(
            self._post_json(
                url=url,
                headers=headers,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
        )

    async def _post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> HttpJsonResponse:
        body = bytearray()
        try:
            async with asyncio.timeout(timeout_seconds):
                async with httpx.AsyncClient(
                    follow_redirects=False,
                    timeout=None,
                    transport=self._transport,
                ) as client:
                    async with client.stream(
                        "POST",
                        url,
                        headers=dict(headers),
                        content=canonical_json(payload).encode("utf-8"),
                    ) as response:
                        status_code = int(response.status_code)
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > self._MAX_RESPONSE_BYTES:
                                body.clear()
                                break
                            body.extend(chunk)
        except TimeoutError as exc:
            raise ProviderProbeError("provider_timeout") from exc
        except httpx.TimeoutException as exc:
            raise ProviderProbeError("provider_timeout") from exc
        except httpx.RequestError as exc:
            raise ProviderProbeError("network_error") from exc
        try:
            decoded: object = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = None
        return HttpJsonResponse(status_code=status_code, payload=decoded)


class NoRedirectHandler(HTTPRedirectHandler):
    """Fail closed instead of following an endpoint-controlled redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


__all__ = ["HttpxDeadlineJsonTransport", "UrllibJsonTransport"]
