"""Sanitized official-SDK fixtures; these tests never start Codex or inference."""

from __future__ import annotations

import json
import threading
import tomllib
from types import SimpleNamespace as S

import pytest

from server.ai_runtime import strategy_research_codex as edge
from server.ai_runtime.external_research_errors import (
    ExternalResearchInvalidResponseError,
    ExternalResearchTimeoutError,
)
from server.ai_runtime.provider_call_window import ProviderExecutionFenced


def notice(method, **payload):
    return S(method=method, payload=S(**payload))


def final(item_id="answer", text='{"drafts": []}'):
    return S(type="agentMessage", id=item_id, phase="final_answer", text=text)


def completed(items=None, status="completed"):
    return notice("turn/completed", turn=S(status=status, items=items or []))


@pytest.fixture
def sdk(monkeypatch):
    state = S(
        clients=[],
        calls=[],
        new_server=False,
        tool_feature_drift=False,
        instruction_sources=[],
        model="gpt-6.1-sol",
        events=[
            notice("item/reasoning/textDelta", delta="PRIVATE_REASONING_NEVER_STORE"),
            notice(
                "thread/tokenUsage/updated",
                token_usage=S(
                    last=S(
                        input_tokens=30,
                        cached_input_tokens=10,
                        output_tokens=12,
                        reasoning_output_tokens=7,
                        total_tokens=42,
                    ),
                    total=S(input_tokens=99999, output_tokens=99999),
                ),
            ),
            notice("item/completed", item=final()),
            completed(
                [
                    final(),
                    S(
                        type="reasoning",
                        id="r",
                        content=["PRIVATE_REASONING_NEVER_STORE"],
                    ),
                ]
            ),
        ],
        block=False,
        released=threading.Event(),
    )

    class Client:
        def __init__(self, config):
            self.config = config
            self.index = len(state.clients)
            self.closed = False
            state.clients.append(self)

        def start(self):
            state.calls.append("start")

        def initialize(self):
            state.calls.append("initialize")
            return S(serverInfo=S(version="0.164.0"))

        def request(self, method, params, *, response_model):
            assert method == "config/read"
            assert params["includeLayers"] is False
            state.calls.append(method)
            # A name containing periods, quotes and unicode must be one TOML key.
            servers = {'private.name"中文': {"enabled": True}}
            for value in self.config.config_overrides:
                if value.startswith("mcp_servers="):
                    overrides = tomllib.loads(value)["mcp_servers"]
                    for name, config in overrides.items():
                        servers.setdefault(name, {}).update(config)
            if self.index == 1 and state.new_server:
                servers["newly-enabled"] = {"enabled": True}
            result = S(
                config=S(
                    mcp_servers=servers,
                    web_search="disabled",
                    project_doc_max_bytes=0,
                    features={
                        **dict.fromkeys(edge._DISABLED_FEATURES, False),
                        "skip_host_skill_discovery": True,
                    },
                )
            )
            if self.index == 1 and state.tool_feature_drift:
                result.config.features["shell_tool"] = True
            return result

        def model_list(self, *, include_hidden):
            assert include_hidden is False
            state.calls.append("model/list")
            return S(
                data=[
                    S(
                        id=state.model,
                        supported_reasoning_efforts=[
                            S(reasoning_effort="high"),
                            S(reasoning_effort="ultra"),
                        ],
                    )
                ]
            )

        def thread_start(self, params):
            state.calls.append("thread/start")
            state.thread_params = params
            assert not any(__import__("pathlib").Path(params["cwd"]).iterdir())
            return S(
                thread=S(id="thread-1"),
                model=state.model,
                model_provider="openai",
                instruction_sources=state.instruction_sources,
                approval_policy=S(root=S(value="never")),
                sandbox=S(root=S(type="readOnly", network_access=False)),
            )

        def turn_start(self, thread_id, input_json, params):
            state.calls.append("turn/start")
            state.turn_params = params
            state.input_json = input_json
            return S(turn=S(id="turn-1"))

        def next_turn_notification(self, turn_id):
            if state.block:
                state.released.wait(timeout=1)
                raise RuntimeError("PRIVATE_SDK_ERROR")
            return state.events.pop(0)

        def turn_interrupt(self, thread_id, turn_id):
            state.calls.append("turn/interrupt")

        def close(self):
            self.closed = True
            state.released.set()

    monkeypatch.setattr(edge, "_sdk", lambda: (Client, lambda **kw: S(**kw), object))
    return state


def invoke(**kwargs):
    return edge.complete_codex_research(
        settings=edge.CodexResearchSettings(),
        system_prompt="NATIVE_SYSTEM_EXACT",
        input_json='{"public":true}',
        timeout_seconds=kwargs.pop("timeout_seconds", 5),
        **kwargs,
    )


def test_single_sdk_turn_has_exact_input_real_usage_and_no_reasoning_persistence(sdk):
    def guard():
        assert sdk.calls[-1] == "thread/start"
        assert "turn/start" not in sdk.calls
        sdk.calls.append("guard")

    text, metadata = invoke(before_model_send=guard)
    assert text == '{"drafts": []}'
    assert sdk.calls.count("turn/start") == 1
    assert len(sdk.clients) == 2 and all(client.closed for client in sdk.clients)
    assert sdk.thread_params["ephemeral"] is True
    assert sdk.thread_params["baseInstructions"] == "NATIVE_SYSTEM_EXACT"
    assert sdk.thread_params["developerInstructions"] == ""
    assert sdk.input_json == '{"public":true}'
    assert sdk.turn_params == {"effort": "ultra", "summary": "none"}
    assert metadata["reasoning_effort_requested"] == "ultra"
    assert metadata["usage"]["input_tokens"] == 30  # last turn, not cumulative total
    assert metadata["response_model"] is None
    assert metadata["server_thread_model"] == "gpt-6.1-sol"
    assert metadata["model_invocation_attempted"] is True
    assert metadata["upstream_network_retry_count"] is None
    assert metadata["output_token_hard_cap_enforced"] is False
    assert metadata["tool_call_count"] == 0
    assert metadata["reasoning_item_count"] == 1
    assert metadata["reasoning_event_count"] == 1
    serialized = json.dumps(metadata)
    assert "PRIVATE" not in serialized and "private.name" not in serialized
    assert all(
        f"features.{name}=false" in sdk.clients[1].config.config_overrides
        for name in edge._DISABLED_FEATURES
    )


def test_changed_mcp_configuration_blocks_before_thread_or_model(sdk):
    sdk.new_server = True
    with pytest.raises(
        ExternalResearchInvalidResponseError, match="codex_mcp_not_disabled"
    ) as error:
        invoke()
    assert "thread/start" not in sdk.calls and "turn/start" not in sdk.calls
    assert error.value.transport_metadata["model_invocation_attempted"] is False
    assert all(client.closed for client in sdk.clients)


def test_tool_config_readback_drift_blocks_before_thread_or_model(sdk):
    sdk.tool_feature_drift = True
    with pytest.raises(
        ExternalResearchInvalidResponseError, match="tool_configuration_changed"
    ):
        invoke()
    assert "thread/start" not in sdk.calls and "turn/start" not in sdk.calls


def test_unavailable_requested_model_never_starts_thread(sdk):
    sdk.model = "different-model"
    with pytest.raises(
        ExternalResearchInvalidResponseError, match="requested_model_unavailable"
    ):
        invoke()
    assert "thread/start" not in sdk.calls and "turn/start" not in sdk.calls


def test_inherited_instructions_block_before_inference_without_exporting_paths(sdk):
    sdk.instruction_sources = ["/private/sensitive/AGENTS.md"]
    with pytest.raises(
        ExternalResearchInvalidResponseError, match="permissions_changed"
    ) as error:
        invoke()
    assert "turn/start" not in sdk.calls
    assert "/private" not in json.dumps(error.value.transport_metadata)


def test_revocation_after_preflight_preserves_guard_exception_and_no_turn(sdk):
    original = ProviderExecutionFenced("worker generation changed")

    def revoked():
        raise original

    with pytest.raises(ProviderExecutionFenced) as error:
        invoke(before_model_send=revoked)
    assert error.value is original
    assert error.value.transport_metadata["turn_start_attempted"] is False
    assert "turn/start" not in sdk.calls


@pytest.mark.parametrize(
    "kind",
    [
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "dynamicToolCall",
        "webSearch",
        "imageView",
    ],
)
def test_tool_attempt_fails_closed_and_interrupts_without_retry(sdk, kind):
    sdk.events = [notice("item/started", item=S(type=kind, id="tool"))]
    with pytest.raises(
        ExternalResearchInvalidResponseError, match="tools_forbidden"
    ) as error:
        invoke()
    assert sdk.calls.count("turn/start") == 1
    assert "turn/interrupt" in sdk.calls
    assert error.value.transport_metadata["tool_call_count"] == 1


def test_model_reroute_is_not_misreported_as_requested_model_success(sdk):
    sdk.events = [notice("model/rerouted", to_model="different-model")]
    with pytest.raises(ExternalResearchInvalidResponseError, match="model_rerouted"):
        invoke()
    assert sdk.calls.count("turn/start") == 1


def test_deadline_interrupts_and_closes_owned_sdk_without_exposing_sdk_error(sdk):
    # Phase-one close normally releases this event; block on a fresh event here.
    sdk.block = True
    sdk.released = threading.Event()
    original_close = None
    client_type, config_type, response_type = edge._sdk()
    original_close = client_type.close

    def close(client):
        client.closed = True
        if client.index == 1:
            sdk.released.set()

    client_type.close = close
    try:
        with pytest.raises(
            ExternalResearchTimeoutError, match="codex_research_timeout"
        ) as error:
            invoke(timeout_seconds=0.03)
    finally:
        client_type.close = original_close
    assert sdk.calls.count("turn/start") == 1
    assert "turn/interrupt" in sdk.calls
    assert all(client.closed for client in sdk.clients)
    assert "PRIVATE" not in str(error.value)
    assert error.value.transport_metadata["model_invocation_attempted"] is True


@pytest.mark.parametrize(
    "change,code",
    [
        ("usage_missing", "usage_required"),
        ("too_many_tokens", "token_limit_exceeded"),
        ("two_finals", "final_message_required"),
        ("failed", "turn_not_completed"),
    ],
)
def test_incomplete_or_unbounded_result_is_rejected_without_resampling(
    sdk, change, code
):
    if change == "usage_missing":
        sdk.events = [notice("item/completed", item=final()), completed([final()])]
    elif change == "too_many_tokens":
        sdk.events[1].payload.token_usage.last.output_tokens = 12289
    elif change == "two_finals":
        sdk.events[-1] = completed([final(), final("second")])
    else:
        sdk.events[-1] = completed([final()], status="failed")
    with pytest.raises(ExternalResearchInvalidResponseError, match=code):
        invoke()
    assert sdk.calls.count("turn/start") == 1


def test_root_wrapped_messages_are_read_as_messages(sdk):
    # This representation is mandatory even without the optional Codex package.
    sdk.events.insert(
        0, notice("item/started", item=S(root=S(type="userMessage", id="u")))
    )
    sdk.events[3] = notice("item/completed", item=S(root=final()))
    text, metadata = invoke()
    assert text == '{"drafts": []}'
    assert metadata["tool_call_count"] == metadata["unsupported_item_count"] == 0


def test_official_generated_thread_items_retain_final_and_reasoning_without_tools(sdk):
    generated = pytest.importorskip(
        "openai_codex.generated.v2_all", reason="optional codex extra"
    )
    user = generated.ThreadItem.model_validate(
        {
            "type": "userMessage",
            "id": "u",
            "content": [{"type": "text", "text": "PUBLIC"}],
        }
    )
    answer = generated.ThreadItem.model_validate(
        {
            "type": "agentMessage",
            "id": "answer",
            "text": '{"drafts": []}',
            "phase": "final_answer",
        }
    )
    reasoning = generated.ThreadItem.model_validate(
        {
            "type": "reasoning",
            "id": "r",
            "summary": [],
            "content": ["PRIVATE_REASONING_NEVER_STORE"],
        }
    )
    assert isinstance(user.root, generated.UserMessageThreadItem)
    assert isinstance(answer.root, generated.AgentMessageThreadItem)
    assert isinstance(reasoning.root, generated.ReasoningThreadItem)
    usage_event = sdk.events[1]
    sdk.events = [
        notice("item/started", item=user),
        notice("item/started", item=reasoning),
        usage_event,
        notice("item/completed", item=answer),
        completed([user, reasoning, answer]),
    ]
    text, metadata = invoke()
    assert text == '{"drafts": []}'
    assert metadata["tool_call_count"] == metadata["unsupported_item_count"] == 0
    assert metadata["reasoning_item_count"] == 1
    assert sdk.calls.count("turn/start") == 1
    assert "PRIVATE" not in json.dumps(metadata)


@pytest.mark.parametrize("kind", ["commandExecution", "mcpToolCall"])
def test_official_generated_tool_items_remain_forbidden(sdk, kind):
    generated = pytest.importorskip(
        "openai_codex.generated.v2_all", reason="optional codex extra"
    )
    data = (
        {
            "type": kind,
            "id": "tool",
            "command": "PRIVATE_COMMAND",
            "commandActions": [],
            "cwd": "/private/fixture",
            "status": "inProgress",
        }
        if kind == "commandExecution"
        else {
            "type": kind,
            "id": "tool",
            "arguments": {"secret": "PRIVATE_ARGUMENT"},
            "server": "PRIVATE_SERVER",
            "tool": "PRIVATE_TOOL",
            "status": "inProgress",
        }
    )
    item = generated.ThreadItem.model_validate(data)
    assert isinstance(
        item.root,
        generated.CommandExecutionThreadItem
        if kind == "commandExecution"
        else generated.McpToolCallThreadItem,
    )
    sdk.events = [notice("item/started", item=item)]
    with pytest.raises(
        ExternalResearchInvalidResponseError, match="tools_forbidden"
    ) as error:
        invoke()
    metadata = error.value.transport_metadata
    assert metadata["tool_call_count"] == 1 and metadata["unsupported_item_count"] == 0
    assert metadata["rejected_item_type"] == kind
    assert sdk.calls.count("turn/start") == 1 and "turn/interrupt" in sdk.calls
    assert "PRIVATE" not in json.dumps(metadata)


@pytest.mark.parametrize(
    "item, safe_type",
    [
        (
            S(type="PRIVATE_UNKNOWN_KIND", id="PRIVATE_ID", text="PRIVATE_CONTENT"),
            "unrecognized",
        ),
        (S(root=S(type="plan", id="p", text="PRIVATE_PLAN")), "plan"),
    ],
)
def test_unsupported_item_is_not_misreported_as_a_tool_call(sdk, item, safe_type):
    sdk.events = [notice("item/started", item=item)]
    with pytest.raises(
        ExternalResearchInvalidResponseError, match="item_type_forbidden"
    ) as error:
        invoke()
    metadata = error.value.transport_metadata
    assert metadata["tool_call_count"] == 0 and metadata["unsupported_item_count"] == 1
    assert metadata["rejected_item_type"] == safe_type
    assert sdk.calls.count("turn/start") == 1 and "turn/interrupt" in sdk.calls
    assert "PRIVATE" not in json.dumps(metadata)


def test_official_unphased_final_uses_last_completed_agent_message(sdk):
    generated = pytest.importorskip(
        "openai_codex.generated.v2_all", reason="optional codex extra"
    )
    earlier = generated.ThreadItem.model_validate(
        {
            "type": "agentMessage",
            "id": "earlier",
            "text": "earlier public answer",
            "phase": None,
        }
    )
    answer = generated.ThreadItem.model_validate(
        {
            "type": "agentMessage",
            "id": "answer",
            "text": '{"drafts": []}',
            "phase": None,
        }
    )
    reasoning = generated.ThreadItem.model_validate(
        {
            "type": "reasoning",
            "id": "r",
            "summary": [],
            "content": ["PRIVATE_REASONING_NEVER_STORE"],
        }
    )
    usage_event = sdk.events[1]
    sdk.events = [
        usage_event,
        notice("item/completed", item=earlier),
        notice("item/completed", item=answer),
        completed([earlier, reasoning, answer]),
    ]
    text, metadata = invoke()
    assert text == '{"drafts": []}'
    assert metadata["final_response_phase"] is None and metadata["unphased_count"] == 2
    assert metadata["tool_call_count"] == metadata["unsupported_item_count"] == 0
    assert metadata["reasoning_item_count"] == 1
    assert "PRIVATE" not in json.dumps(metadata)


def test_official_explicit_final_takes_priority_over_later_unphased_or_commentary(sdk):
    generated = pytest.importorskip(
        "openai_codex.generated.v2_all", reason="optional codex extra"
    )
    answer = generated.ThreadItem.model_validate(
        {
            "type": "agentMessage",
            "id": "answer",
            "text": '{"drafts": []}',
            "phase": "final_answer",
        }
    )
    unphased = generated.ThreadItem.model_validate(
        {
            "type": "agentMessage",
            "id": "unknown",
            "text": "later unphased message",
            "phase": None,
        }
    )
    commentary = generated.ThreadItem.model_validate(
        {
            "type": "agentMessage",
            "id": "commentary",
            "text": "PRIVATE_COMMENTARY_NEVER_STORE",
            "phase": "commentary",
        }
    )
    usage_event = sdk.events[1]
    sdk.events = [
        usage_event,
        notice("item/completed", item=answer),
        completed([answer, unphased, commentary]),
    ]
    text, metadata = invoke()
    assert text == '{"drafts": []}'
    assert (
        metadata["final_response_phase"] == "final_answer"
        and metadata["unphased_count"] == 1
    )
    assert "PRIVATE" not in json.dumps(metadata)


def test_commentary_and_reasoning_alone_never_become_a_final(sdk):
    commentary = S(
        root=S(
            type="agentMessage", id="c", text="PRIVATE_COMMENTARY", phase="commentary"
        )
    )
    reasoning = S(root=S(type="reasoning", id="r", content=["PRIVATE_REASONING"]))
    sdk.events = [
        sdk.events[1],
        notice("item/completed", item=commentary),
        completed([commentary, reasoning]),
    ]
    with pytest.raises(
        ExternalResearchInvalidResponseError, match="final_message_required"
    ) as error:
        invoke()
    assert error.value.transport_metadata["unphased_count"] == 0
    assert "PRIVATE" not in json.dumps(error.value.transport_metadata)
