"""Provider adapter for a fixed, non-financial connectivity probe."""

from __future__ import annotations

from .contracts import content_fingerprint
from .openai_compatibility import safe_usage
from .provider_call_window import ProviderSendAdmission
from .provider_connectivity_contracts import (
    CONNECTIVITY_PROBE_TOKEN,
    JsonHttpTransport,
    ProviderConnectivitySettings,
    ProviderProbeError,
    ProviderProbeResponse,
)


class OpenAICompatibleConnectivityAdapter:
    """One-turn connectivity adapter with no tools or financial context."""

    def __init__(
        self,
        settings: ProviderConnectivitySettings,
        transport: JsonHttpTransport,
        *,
        send_admission: ProviderSendAdmission | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._send_admission = send_admission

    def probe(self) -> ProviderProbeResponse:
        payload = {
            "model": self._settings.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "This is a non-financial connectivity probe. Do not call "
                        "tools. Return only the exact token requested by the user."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Return exactly: {CONNECTIVITY_PROBE_TOKEN}",
                },
            ],
            "max_tokens": 128,
            "temperature": 0,
            "stream": False,
        }
        if self._send_admission is not None:
            self._send_admission.require_allowed()
        response = self._transport.post_json(
            url=self._settings.endpoint_url,
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Karkinos-AI-Connectivity/1",
            },
            payload=payload,
            timeout_seconds=self._settings.timeout_seconds,
        )
        if response.status_code in {401, 403}:
            raise ProviderProbeError(
                "provider_authentication_failed", http_status=response.status_code
            )
        if response.status_code == 429:
            raise ProviderProbeError(
                "provider_rate_limited", http_status=response.status_code
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderProbeError(
                "provider_http_error", http_status=response.status_code
            )
        body = response.payload
        if not isinstance(body, dict):
            raise ProviderProbeError(
                "provider_invalid_json", http_status=response.status_code
            )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderProbeError(
                "provider_invalid_response", http_status=response.status_code
            )
        first_choice = choices[0]
        message = (
            first_choice.get("message") if isinstance(first_choice, dict) else None
        )
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or CONNECTIVITY_PROBE_TOKEN not in content:
            raise ProviderProbeError(
                "provider_probe_token_mismatch", http_status=response.status_code
            )
        return ProviderProbeResponse(
            http_status=response.status_code,
            request_payload_fingerprint=content_fingerprint(payload),
            response_fingerprint=content_fingerprint(body),
            response_model=str(body.get("model") or self._settings.model_name),
            usage=safe_usage(body.get("usage")),
        )


__all__ = ["OpenAICompatibleConnectivityAdapter"]
