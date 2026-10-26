"""Official local Codex SDK completion edge; no credential or RPC implementation."""

from __future__ import annotations

import importlib
import json
import math
import os
import tempfile
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.external_research_errors import (
    ExternalResearchInvalidResponseError,
    ExternalResearchNetworkError,
    ExternalResearchTimeoutError,
)
from server.ai_runtime.provider_call_window import ProviderExecutionFenced
from server.ai_runtime.provider_connectivity_contracts import (
    ConnectivityConfigurationError,
    ProviderConnectivitySettings,
)
from server.contracts.strategy_research import (
    STRATEGY_RESEARCH_MAX_OUTPUT_TOKENS,
    StrategyResearchRejected,
)

# These tool/capability switches were checked against `codex features list`.
# Read-only sandbox alone does not prevent a tool from reading local data.
_DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "unified_exec_tty",
    "apps",
    "multi_agent",
    "multi_agent_v2",
    "multi_agent_v2_dynamic_tools",
    "hooks",
    "plugins",
    "remote_plugin",
    "plugin_sharing",
    "skill_search",
    "skill_mcp_dependency_install",
    "view_image",
    "image_generation",
    "computer_use",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "in_app_browser",
    "code_mode",
    "code_mode_host",
    "code_mode_tool_search",
    "workspace_dependencies",
    "goals",
    "sleep_tool",
    "memories",
    "tool_suggest",
    "unbounded_connection_retries",
)
_TOOL_ITEM_TYPES = frozenset(
    {
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "dynamicToolCall",
        "collabAgentToolCall",
        "webSearch",
        "imageView",
        "sleep",
        "imageGeneration",
    }
)
# These are recognized SDK item labels, but not a permitted message or a tool call.
_OTHER_ITEM_TYPES = frozenset(
    {
        "hookPrompt",
        "functionCallOutput",
        "plan",
        "subAgentActivity",
        "enteredReviewMode",
        "exitedReviewMode",
        "contextCompaction",
    }
)

_OVERRIDES = (
    'model_provider="openai"',
    'approval_policy="never"',
    'sandbox_mode="read-only"',
    'web_search="disabled"',
    'model_reasoning_summary="none"',
    "project_doc_max_bytes=0",
    "features.skip_host_skill_discovery=true",
    *(f"features.{name}=false" for name in _DISABLED_FEATURES),
)


@dataclass(frozen=True)
class CodexResearchSettings:
    """Explicit research-only selection; managed login stays inside Codex."""

    model_name: str = "gpt-6.1-sol"
    provider_id: str = "codex"
    codex_bin: str | None = None
    reasoning_effort: str = "ultra"
    timeout_seconds: float = 600.0
    enabled: bool = True
    adapter_kind: str = "codex_app_server_rpc"
    credential_source: str = "codex_managed_login"

    def __post_init__(self) -> None:
        if (
            not self.enabled
            or not self.model_name.strip()
            or not self.provider_id.strip()
        ):
            raise ConnectivityConfigurationError(
                "Codex research provider is disabled or unnamed"
            )
        if self.adapter_kind != "codex_app_server_rpc":
            raise ConnectivityConfigurationError(
                "Codex research requires official SDK RPC"
            )
        if self.reasoning_effort not in {
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        }:
            raise ConnectivityConfigurationError(
                "Codex reasoning effort is unsupported"
            )
        if (
            not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 600
        ):
            raise ConnectivityConfigurationError(
                "Codex research timeout must be within (0, 600]"
            )

    @property
    def model_id(self) -> str:
        return f"{self.provider_id}:{self.model_name}"

    @property
    def endpoint_origin(self) -> str:
        return "codex-app-server://local"


StrategyResearchSettings = ProviderConnectivitySettings | CodexResearchSettings


def _sdk() -> tuple[Any, Any, Any]:
    try:
        client = importlib.import_module("openai_codex.client")
        generated = importlib.import_module("openai_codex.generated.v2_all")
    except ImportError:
        raise ConnectivityConfigurationError(
            "install the optional codex extra"
        ) from None
    return client.CodexClient, client.CodexConfig, generated.ConfigReadResponse


def _value(value: Any) -> Any:
    value = getattr(value, "root", value)
    return getattr(value, "value", value)


def _field(value: Any, name: str, default: Any = None) -> Any:
    # Generated union types (including ThreadItem) use Pydantic RootModel.
    value = _value(value)
    return (
        value.get(name, default)
        if isinstance(value, Mapping)
        else getattr(value, name, default)
    )


def _mcp_states(client: Any, response_type: Any, cwd: str) -> dict[str, bool]:
    response = client.request(
        "config/read",
        {"cwd": cwd, "includeLayers": False},
        response_model=response_type,
    )
    features = _field(response.config, "features", {})
    if (
        not isinstance(features, Mapping)
        or any(features.get(name) is not False for name in _DISABLED_FEATURES)
        or features.get("skip_host_skill_discovery") is not True
        or _value(_field(response.config, "web_search")) != "disabled"
        or _field(response.config, "project_doc_max_bytes") != 0
    ):
        raise ExternalResearchInvalidResponseError("codex_tool_configuration_changed")
    servers = _field(response.config, "mcp_servers", {})
    if not isinstance(servers, Mapping):
        raise ExternalResearchInvalidResponseError("codex_mcp_config_invalid")
    result = {}
    for name, config in servers.items():
        if not isinstance(name, str) or not isinstance(config, Mapping):
            raise ExternalResearchInvalidResponseError("codex_mcp_config_invalid")
        enabled = config.get("enabled", True)
        if type(enabled) is not bool:
            raise ExternalResearchInvalidResponseError("codex_mcp_config_invalid")
        result[name] = enabled
    return result


def _interrupt_and_close(
    client: Any, thread_id: str | None, turn_id: str | None
) -> None:
    if thread_id is not None and turn_id is not None:

        def interrupt() -> None:
            try:
                client.turn_interrupt(thread_id, turn_id)
            except Exception:
                pass  # Never persist SDK messages, headers or model reasoning.

        worker = threading.Thread(target=interrupt, daemon=True)
        worker.start()
        worker.join(timeout=0.2)
    client.close()


def complete_codex_research(
    *,
    settings: CodexResearchSettings,
    system_prompt: str,
    input_json: str,
    timeout_seconds: float,
    before_model_send: Callable[[], None] | None = None,
) -> tuple[str, JsonObject]:
    """One official SDK turn after metadata-only capability checks, never a retry.

    The SDK owns authentication and stdio. We retain only final text and safe
    counters, not raw notifications, reasoning, account/config values or paths.
    """
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600:
        raise ConnectivityConfigurationError(
            "Codex research timeout must be within (0, 600]"
        )
    metadata: JsonObject = {
        "transport_kind": settings.adapter_kind,
        "requested_model": settings.model_name,
        "reasoning_effort_requested": settings.reasoning_effort,
        "response_model": None,
        "upstream_model_identity_verified": False,
        "project_platform_https_api_called": False,
        "model_invocation_attempted": False,
        "turn_start_attempted": False,
        "project_automatic_retry_count": 0,
        "upstream_network_attempt_count": None,
        "upstream_network_retry_count": None,
        "output_token_hard_cap_enforced": False,
        "output_token_rejection_after_reply": STRATEGY_RESEARCH_MAX_OUTPUT_TOKENS,
        "usage": {},
        "reasoning_event_count": 0,
        "tool_call_count": 0,
        "unsupported_item_count": 0,
        "phase": "sdk_preflight",
    }
    state: dict[str, Any] = {"client": None, "thread_id": None, "turn_id": None}
    expired = threading.Event()
    deadline_stopped = threading.Event()

    def deadline() -> None:
        if deadline_stopped.wait(timeout_seconds):
            return
        expired.set()
        if state["client"] is not None:
            _interrupt_and_close(state["client"], state["thread_id"], state["turn_id"])

    deadline_thread = threading.Thread(target=deadline, daemon=True)
    try:
        client_type, config_type, config_response_type = _sdk()
        deadline_thread.start()
        with tempfile.TemporaryDirectory(prefix="karkinos-codex-research-") as cwd:
            # Only names are inspected; the values of parent environment secrets
            # are never read/copied by this adapter. Codex manages its own login.
            blank_env = {
                name: ""
                for name in os.environ
                if name.startswith("KARKINOS_")
                or name
                in {
                    "OPENAI_API_KEY",
                    "CODEX_API_KEY",
                    "CODEX_ACCESS_TOKEN",
                    "OPENAI_BASE_URL",
                    "OPENAI_API_BASE",
                    "CODEX_API_ENDPOINT",
                }
            }

            def start(overrides: tuple[str, ...]) -> Any:
                client = client_type(
                    config_type(
                        codex_bin=settings.codex_bin,
                        cwd=cwd,
                        config_overrides=overrides,
                        env=blank_env,
                        experimental_api=False,
                        client_name="karkinos_strategy_research",
                        client_title="Karkinos strategy research",
                    )
                )
                state["client"] = client
                if expired.is_set():
                    raise ExternalResearchTimeoutError("codex_research_timeout")
                client.start()
                if expired.is_set():
                    client.close()
                    raise ExternalResearchTimeoutError("codex_research_timeout")
                initialized = client.initialize()
                info = _field(
                    initialized, "server_info", _field(initialized, "serverInfo")
                )
                metadata["sdk_runtime_version"] = _field(info, "version") or getattr(
                    client, "_runtime_version", None
                )
                try:
                    metadata["sdk_package_version"] = package_version("openai-codex")
                except PackageNotFoundError:
                    metadata["sdk_package_version"] = None
                return client

            client = start(_OVERRIDES)
            states = _mcp_states(client, config_response_type, cwd)
            client.close()
            # Empty-table override merges inherited servers. One quoted TOML
            # inline table safely disables names containing periods/quotes.
            mcp_override = (
                "mcp_servers={"
                + ",".join(
                    json.dumps(name, ensure_ascii=False) + "={enabled=false}"
                    for name in states
                )
                + "}"
            )
            client = start((*_OVERRIDES, mcp_override))
            final_states = _mcp_states(client, config_response_type, cwd)
            if any(final_states.values()):
                raise ExternalResearchInvalidResponseError("codex_mcp_not_disabled")
            metadata["mcp_server_count"] = len(final_states)
            metadata["all_mcp_disabled"] = True
            metadata["tool_features_disabled"] = True
            models = client.model_list(include_hidden=False)
            model = next((m for m in models.data if m.id == settings.model_name), None)
            if model is None or settings.reasoning_effort not in {
                _value(item.reasoning_effort)
                for item in model.supported_reasoning_efforts
            }:
                raise ExternalResearchInvalidResponseError(
                    "codex_requested_model_unavailable"
                )
            if expired.is_set():
                raise ExternalResearchTimeoutError("codex_research_timeout")
            params = {
                "model": settings.model_name,
                "modelProvider": "openai",
                "cwd": cwd,
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "ephemeral": True,
                "baseInstructions": system_prompt,
                "developerInstructions": "",
            }
            started = client.thread_start(params)
            state["thread_id"] = started.thread.id
            metadata["server_thread_model"] = started.model
            metadata["instruction_source_count"] = len(
                started.instruction_sources or []
            )
            sandbox = _field(started.sandbox, "root", started.sandbox)
            if (
                started.model != settings.model_name
                or started.model_provider != "openai"
                or _value(started.approval_policy) != "never"
                or _field(sandbox, "type") != "readOnly"
                or _field(sandbox, "network_access", False) is not False
                or metadata["instruction_source_count"] != 0
            ):
                raise ExternalResearchInvalidResponseError(
                    "codex_thread_permissions_changed"
                )
            if before_model_send is not None:
                before_model_send()
            if expired.is_set():
                raise ExternalResearchTimeoutError("codex_research_timeout")
            turn_params = {"effort": settings.reasoning_effort, "summary": "none"}
            metadata["sdk_request_fingerprint"] = content_fingerprint(
                {
                    "thread_start": params,
                    "turn_start": {"input": input_json, **turn_params},
                }
            )
            metadata.update(
                phase="turn_start",
                turn_start_attempted=True,
                model_invocation_attempted=True,
            )
            turn = client.turn_start(started.thread.id, input_json, turn_params)
            state["turn_id"] = turn.turn.id
            finals: dict[str, str] = {}
            unphased: dict[str, str] = {}
            reasoning_ids: set[str] = set()

            def inspect_item(item: Any, *, completed: bool) -> None:
                kind, item_id = _field(item, "type"), _field(item, "id")
                kind = kind if isinstance(kind, str) else None
                if kind == "reasoning":
                    reasoning_ids.add(str(item_id))
                elif kind == "agentMessage":
                    phase = _value(_field(item, "phase"))
                    if completed and phase in {None, "final_answer"}:
                        text = _field(item, "text")
                        if not isinstance(text, str) or not isinstance(item_id, str):
                            raise ExternalResearchInvalidResponseError(
                                "codex_final_message_invalid"
                            )
                        messages = finals if phase == "final_answer" else unphased
                        if item_id in messages and messages[item_id] != text:
                            raise ExternalResearchInvalidResponseError(
                                "codex_final_message_changed"
                            )
                        messages[item_id] = text
                elif kind in _TOOL_ITEM_TYPES:
                    metadata["tool_call_count"] += 1
                    metadata["rejected_item_type"] = kind
                    raise ExternalResearchInvalidResponseError("codex_tools_forbidden")
                elif kind != "userMessage":
                    metadata["unsupported_item_count"] += 1
                    # Persist only reviewed SDK discriminators, never unknown data.
                    metadata["rejected_item_type"] = (
                        kind if kind in _OTHER_ITEM_TYPES else "unrecognized"
                    )
                    raise ExternalResearchInvalidResponseError(
                        "codex_item_type_forbidden"
                    )

            while True:
                notification = client.next_turn_notification(turn.turn.id)
                method, payload = notification.method, notification.payload
                if "reasoning" in method.lower():
                    metadata["reasoning_event_count"] += 1
                    continue
                if method in {"item/started", "item/completed"}:
                    inspect_item(payload.item, completed=method == "item/completed")
                elif method == "model/rerouted":
                    raise ExternalResearchInvalidResponseError("codex_model_rerouted")
                elif method == "thread/tokenUsage/updated":
                    usage = payload.token_usage.last
                    keys = (
                        "input_tokens",
                        "cached_input_tokens",
                        "output_tokens",
                        "reasoning_output_tokens",
                        "total_tokens",
                    )
                    values = {key: getattr(usage, key) for key in keys}
                    if any(type(v) is not int or v < 0 for v in values.values()):
                        raise ExternalResearchInvalidResponseError(
                            "codex_usage_invalid"
                        )
                    metadata["usage"] = values
                elif method == "error":
                    raise ExternalResearchInvalidResponseError("codex_turn_error")
                elif method == "turn/completed":
                    metadata["finish_reason"] = _value(payload.turn.status)
                    for item in payload.turn.items:
                        inspect_item(item, completed=True)
                    if metadata["finish_reason"] != "completed":
                        raise ExternalResearchInvalidResponseError(
                            "codex_turn_not_completed"
                        )
                    break
            if expired.is_set():
                raise ExternalResearchTimeoutError("codex_research_timeout")
            metadata["unphased_count"] = len(unphased)
            if len(finals) > 1 or not (finals or unphased):
                raise ExternalResearchInvalidResponseError(
                    "codex_final_message_required"
                )
            # Match the official SDK: explicit final first, otherwise the last
            # completed unphased agent message. Commentary/reasoning never qualify.
            if finals:
                content = next(iter(finals.values()))
                metadata["final_response_phase"] = "final_answer"
            else:
                content = next(reversed(unphased.values()))
                metadata["final_response_phase"] = None
            if not content.strip():
                raise ExternalResearchInvalidResponseError(
                    "codex_final_message_required"
                )
            if not metadata["usage"]:
                raise ExternalResearchInvalidResponseError("codex_usage_required")
            if metadata["usage"]["output_tokens"] > STRATEGY_RESEARCH_MAX_OUTPUT_TOKENS:
                raise ExternalResearchInvalidResponseError(
                    "codex_output_token_limit_exceeded"
                )
            metadata.update(phase="completed", reasoning_item_count=len(reasoning_ids))
            return content, metadata
    except Exception as exc:
        metadata["safe_sdk_exception_class"] = type(exc).__name__
        if expired.is_set():
            error: Exception = ExternalResearchTimeoutError("codex_research_timeout")
        elif isinstance(
            exc,
            (
                ConnectivityConfigurationError,
                ExternalResearchInvalidResponseError,
                ExternalResearchTimeoutError,
                StrategyResearchRejected,
                ProviderExecutionFenced,
            ),
        ):
            error = exc
        else:
            error = ExternalResearchNetworkError("codex_sdk_transport_failed")
        setattr(error, "transport_metadata", dict(metadata))
        raise error from None
    finally:
        deadline_stopped.set()
        if state["client"] is not None:
            if metadata["phase"] != "completed":
                _interrupt_and_close(
                    state["client"], state["thread_id"], state["turn_id"]
                )
            else:
                state["client"].close()
