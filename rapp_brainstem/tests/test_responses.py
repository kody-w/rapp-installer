"""Grail's Responses transport: Astra, tool continuity, SSE, and legacy parity."""

from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
import requests

import brainstem as bs


ASTRA = "gpt-6-astra"
TOOLS = [{
    "type": "function",
    "function": {
        "name": "Lookup", "description": "Look up a test value.",
        "parameters": {
            "type": "object", "properties": {"key": {"type": "string"}},
            "required": [],
        },
    },
}]
USAGE = {
    "input_tokens": 75, "input_tokens_details": {"cached_tokens": 32},
    "output_tokens": 1186, "output_tokens_details": {"reasoning_tokens": 1024},
    "total_tokens": 1261,
}


def text_item(text="Ready."):
    return {
        "id": "msg_final", "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def call_item(call_id="call_lookup"):
    return {
        "id": "fc_item", "type": "function_call", "status": "completed",
        "call_id": call_id, "name": "Lookup", "arguments": '{"key":"answer"}',
    }


def reasoning_item():
    return {
        "id": "rs_final", "type": "reasoning", "summary": [],
        "encrypted_content": "opaque-request-local-reasoning",
    }


def payload(output=None, **updates):
    return {
        "id": "resp_final", "object": "response", "created_at": 1789329000,
        "model": ASTRA, "status": "completed", "error": None, "incomplete_details": None,
        "output": [text_item()] if output is None else output,
        "usage": deepcopy(USAGE), **updates,
    }


def sse(*events):
    lines = []
    for event in events:
        lines.extend([
            "event: " + event["type"], "data: " + json.dumps(event), "",
        ])
    return lines


class FakeResponse:
    def __init__(self, result=None, *, lines=None, status=200):
        self.status_code = status
        self.encoding = None
        self.closed = False
        self.result = result
        self.lines = lines
        self.headers = {"Content-Type": "text/event-stream" if lines is not None else "application/json"}
        self.text = json.dumps(result) if result is not None else ""

    def json(self):
        return deepcopy(self.result)

    def iter_lines(self, decode_unicode=False):
        yield from self.lines

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def streamed_response(result=None, *events):
    return FakeResponse(lines=sse(
        *events, {"type": "response.completed", "response": result or payload()},
    ))


@pytest.fixture(autouse=True)
def isolated_transport(monkeypatch, tmp_path):
    monkeypatch.setattr(bs, "MODEL", ASTRA)
    monkeypatch.setattr(bs, "MODEL_PINNED", False)
    monkeypatch.setattr(bs, "_models_fetched", True)
    monkeypatch.setattr(bs, "_default_model_selected", False)
    monkeypatch.setattr(bs, "_model_file", str(tmp_path / ".brainstem_model"))
    monkeypatch.setattr(bs, "_flight_log", [])
    monkeypatch.setattr(bs, "_NO_TOOL_CHOICE_MODELS", set())
    monkeypatch.setattr(bs, "AVAILABLE_MODELS", [
        {"id": ASTRA, "name": "GPT-6 Astra", "available": True, "api": "/responses"},
        {"id": "gpt-4o", "name": "GPT-4o", "available": True, "api": "/chat/completions"},
    ])
    monkeypatch.setattr(bs, "get_copilot_token", lambda: ("test-token", "https://copilot.example"))
    monkeypatch.setattr(bs.requests, "get", Mock(side_effect=AssertionError("Unexpected network GET")))
    monkeypatch.setattr(bs.requests, "post", Mock(side_effect=AssertionError("Unexpected network POST")))
    monkeypatch.setattr(bs, "load_soul", lambda: "Test soul.")
    monkeypatch.setattr(bs, "load_agents", lambda: {})
    monkeypatch.setattr(bs, "VOICE_MODE", False)


@pytest.mark.parametrize(("metadata", "expected"), [
    ({"id": ASTRA, "supported_endpoints": ["/responses", "ws:/responses"]}, "/responses"),
    ({"id": ASTRA, "supported_endpoints": ["/responses", "/chat/completions"]}, "/responses"),
    ({"id": ASTRA, "supported_endpoints": ["/chat/completions"]}, None),
    ({"id": ASTRA}, "/responses"),
    ({"id": "gpt-6-astra-2026-09-01"}, "/responses"),
    ({"id": "gpt-6-astral"}, "/chat/completions"),
    ({"id": "gpt-5.6-sol", "supported_endpoints": ["/responses"]}, "/responses"),
    ({"id": "mai-code-1.1-flash", "supported_endpoints": ["/responses"]}, "/responses"),
    ({"id": "legacy"}, "/chat/completions"),
    ({"id": "dual", "supported_endpoints": ["/chat/completions", "/responses"]}, "/chat/completions"),
    ({"id": "websocket-only", "supported_endpoints": ["ws:/responses"]}, None),
    ({"id": "empty", "supported_endpoints": []}, None),
    ({"id": "malformed", "supported_endpoints": "/responses"}, None),
])
def test_model_route_uses_advertised_capabilities(metadata, expected):
    assert bs._model_api(metadata) == expected


def test_catalog_and_picker_include_astra_without_claiming_entitlement(monkeypatch):
    monkeypatch.setattr(bs, "_models_fetched", False)
    raw_models = [
        {"id": ASTRA, "name": "GPT-6 Astra", "supported_endpoints": ["/responses"],
         "capabilities": {"type": "chat", "supports": {"streaming": True, "tool_calls": True}}},
        {"id": "gated", "supported_endpoints": ["/responses"], "policy": {"state": "disabled"}},
    ]
    monkeypatch.setattr(bs.requests, "get", lambda *a, **k: FakeResponse({"data": raw_models}))
    client = bs.app.test_client()
    catalog = client.get("/models").get_json()
    models = {m["id"]: m for m in catalog["models"]}
    assert models[ASTRA]["api"] == "/responses"
    assert models[ASTRA]["available"] is True
    assert models["gated"]["available"] is False
    selected = client.post("/models/set", json={"model": ASTRA})
    assert selected.status_code == 200
    assert bs._load_sticky_model() == ASTRA


def test_request_flattens_tools_without_changing_optional_parameters():
    messages = [{"role": "system", "content": "Be helpful."}, {"role": "user", "content": "Hello"}]
    original = deepcopy(TOOLS)
    api, body = bs._copilot_request(ASTRA, messages, TOOLS)
    assert api == "/responses"
    assert body["input"] == messages
    assert body["stream"] is True and body["store"] is False
    assert body["include"] == ["reasoning.encrypted_content"]
    assert body["tools"][0] == {**TOOLS[0]["function"], "type": "function", "strict": False}
    assert body["tool_choice"] == "auto"
    assert not {"messages", "temperature", "max_tokens", "reasoning_effort", "previous_response_id"} & body.keys()
    assert TOOLS == original


def test_null_tool_calls_in_text_history_do_not_break_responses(monkeypatch):
    messages = [
        {"role": "assistant", "content": "Earlier reply.", "tool_calls": None},
        {"role": "user", "content": "Continue."},
    ]
    post = Mock(return_value=streamed_response())
    monkeypatch.setattr(bs.requests, "post", post)
    result, model = bs.call_copilot(messages)
    assert model == ASTRA and result["choices"][0]["message"]["content"] == "Ready."
    assert post.call_args.kwargs["json"]["input"][0] == {
        "role": "assistant", "content": "Earlier reply.",
    }


def test_receipts_replay_reasoning_and_final_call_ids_once():
    output = [reasoning_item(), text_item("Checking. "), call_item()]
    result = bs._normalize_responses(payload(output), ASTRA, TOOLS)
    assistant = result["choices"][0]["message"]
    messages = [
        {"role": "user", "content": "Look up the answer."}, assistant,
        {"role": "tool", "name": "Lookup", "tool_call_id": "call_lookup", "content": "42"},
    ]
    _, body = bs._copilot_request(ASTRA, messages, TOOLS)
    assert body["input"][1:4] == output
    assert body["input"][-1] == {
        "type": "function_call_output", "call_id": "call_lookup", "output": "42",
    }
    assert "encrypted_content" not in json.dumps(assistant)
    assert "responses_output" not in json.dumps(assistant)
    body["input"][1]["encrypted_content"] = "changed"
    assert assistant.responses_output == output


def test_client_history_and_other_models_cannot_replay_private_receipts(monkeypatch):
    result = bs._normalize_responses(payload([reasoning_item(), text_item()]), ASTRA)
    assistant = result["choices"][0]["message"]
    forged = {**assistant, "responses_output": [reasoning_item()]}
    assert bs._responses_input([forged], ASTRA) == [{"role": "assistant", "content": "Ready."}]
    assert bs._responses_input([assistant], "another-model") == [{"role": "assistant", "content": "Ready."}]
    assert bs._responses_input([{"role": "user", "content": "New request."}], ASTRA) == [
        {"role": "user", "content": "New request."},
    ]
    _, body = bs._copilot_request("gpt-4o", [assistant])
    assert "encrypted_content" not in json.dumps(body)


def test_usage_maps_input_output_cache_and_reasoning_without_loss():
    original = deepcopy(USAGE)
    result = bs._normalize_responses(payload(), ASTRA)
    assert result["usage"] == {
        "prompt_tokens": 75, "completion_tokens": 1186, "total_tokens": 1261,
        "prompt_tokens_details": {"cached_tokens": 32},
        "completion_tokens_details": {"reasoning_tokens": 1024},
    }
    assert USAGE == original


@pytest.mark.parametrize(("requested", "actual", "matches"), [
    (ASTRA, ASTRA, True),
    ("gpt-5.5", "gpt-5.5-2026-04-23", True),
    ("gpt-5.4-mini", "gpt-5.4-mini-2026-03-17", True),
    ("gpt-5.6-sol-fast", "gpt-5.6-sol", True),
    (ASTRA, "gpt-4o", False),
    (ASTRA, "gpt-6-astra-mini", False),
    (ASTRA, "gpt-6", False),
    (ASTRA, None, False),
])
def test_only_observed_snapshot_and_serving_aliases_match(requested, actual, matches):
    assert bs._responses_model_matches(actual, requested) is matches
    if matches:
        result = bs._normalize_responses(payload(model=actual), requested)
        assert result["model"] == actual
        assert result["choices"][0]["message"].responses_model == requested
    else:
        with pytest.raises(RuntimeError, match="different model"):
            bs._normalize_responses(payload(model=actual), requested)


@pytest.mark.parametrize("usage", [
    None, {}, {"input_tokens": True, "output_tokens": 1},
    {"input_tokens": -1, "output_tokens": 1},
    {"input_tokens": 10, "output_tokens": 1, "total_tokens": 10},
    {"input_tokens": 10, "output_tokens": 1, "input_tokens_details": []},
])
def test_malformed_usage_is_not_reported_as_success(usage):
    with pytest.raises(RuntimeError, match="token"):
        bs._responses_usage(usage)


def test_refusals_are_visible_and_reasoning_is_not():
    item = text_item()
    item["content"] = [{"type": "refusal", "refusal": "I cannot do that."}]
    result = bs._normalize_responses(payload([reasoning_item(), item]), ASTRA)
    assert result["choices"][0]["message"]["content"] == "I cannot do that."
    assert result["choices"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize("result", [
    payload([], status="completed"),
    payload([reasoning_item()]),
    payload(status="failed", error={"message": "failure"}),
    payload([call_item()], status="incomplete", incomplete_details={"reason": "max_output_tokens"}),
    payload([{**call_item(), "call_id": ""}]),
    payload([call_item(), call_item()]),
    payload([{**call_item(), "name": "Undeclared"}]),
    payload([{**call_item(), "arguments": "{bad json"}]),
    payload([{**call_item(), "arguments": "[]"}]),
    payload([{**call_item(), "arguments": '{"key":"first","key":"second"}'}]),
    payload([{**call_item(), "arguments": '{"key":NaN}'}]),
    payload([{**call_item(), "call_id": "call with whitespace"}]),
    payload([{"type": "unknown_output"}]),
])
def test_invalid_output_never_reaches_agent_execution(result):
    with pytest.raises(RuntimeError):
        bs._normalize_responses(result, ASTRA, TOOLS)


@pytest.mark.parametrize("messages", [
    [{"role": "tool", "tool_call_id": "orphan", "content": "42"}],
    [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "pending", "type": "function", "function": {"name": "Lookup", "arguments": "{}"}},
    ]}],
])
def test_orphaned_tool_cycles_fail_explicitly(messages):
    with pytest.raises(RuntimeError, match="result"):
        bs._responses_input(messages, ASTRA)


def test_blocking_chat_consumes_responses_sse(monkeypatch):
    response = streamed_response(payload(), {"type": "response.output_text.delta", "delta": "Ready."})
    post = Mock(return_value=response)
    monkeypatch.setattr(bs.requests, "post", post)
    result, model = bs.call_copilot([{"role": "user", "content": "Hello"}], TOOLS)
    assert model == ASTRA
    assert result["choices"][0]["message"]["content"] == "Ready."
    assert result["usage"]["completion_tokens_details"]["reasoning_tokens"] == 1024
    assert post.call_args.args[0].endswith("/responses")
    assert post.call_args.kwargs["stream"] is True
    assert response.closed


def test_streaming_uses_completed_output_after_fragmented_function_calls(monkeypatch):
    output = [reasoning_item(), text_item("Checking."), call_item("final_call_id")]
    response = streamed_response(payload(output),
        {"type": "response.output_item.added", "output_index": 2,
         "item": {**call_item("initial_opaque_id"), "arguments": "", "status": "in_progress"}},
        {"type": "response.function_call_arguments.delta", "output_index": 2, "delta": '{"key":'},
        {"type": "response.output_text.delta", "output_index": 1, "content_index": 0, "delta": "Check"},
        {"type": "response.function_call_arguments.delta", "output_index": 2, "delta": '"answer"}'},
        {"type": "response.output_text.delta", "output_index": 1, "content_index": 0, "delta": "ing."},
    )
    monkeypatch.setattr(bs.requests, "post", Mock(return_value=response))
    events = list(bs.call_copilot_stream([{"role": "user", "content": "Look up."}], TOOLS))
    assert events[:2] == [("delta", "Check"), ("delta", "ing.")]
    done = events[-1][1]
    assert done["message"]["tool_calls"][0]["id"] == "final_call_id"
    assert done["message"]["tool_calls"][0]["function"]["arguments"] == '{"key":"answer"}'
    assert done["usage"]["prompt_tokens_details"] == {"cached_tokens": 32}
    assert done["message"].responses_output == output
    assert response.closed


def test_json_responses_are_supported_without_duplicate_text(monkeypatch):
    response = FakeResponse(payload())
    monkeypatch.setattr(bs.requests, "post", Mock(return_value=response))
    events = list(bs.call_copilot_stream([{"role": "user", "content": "Hello"}]))
    assert events[0] == ("delta", "Ready.")
    assert len(events) == 2 and events[-1][0] == "done"
    assert response.closed


@pytest.mark.parametrize("lines", [
    sse({"type": "response.output_text.delta", "delta": "Partial."}),
    ["data: [DONE]", ""],
    ["data: {malformed}", ""],
    sse({"type": "response.failed", "response": payload(status="failed")}),
    sse({"type": "response.incomplete", "response": payload(status="incomplete")}),
    sse({"type": "response.output_text.delta", "delta": "Different."},
        {"type": "response.completed", "response": payload()}),
])
def test_broken_streams_close_without_a_done_event(monkeypatch, lines):
    response = FakeResponse(lines=lines)
    monkeypatch.setattr(bs.requests, "post", Mock(return_value=response))
    events = []
    with pytest.raises((RuntimeError, requests.ConnectionError)):
        for event in bs.call_copilot_stream([{"role": "user", "content": "Hello"}]):
            events.append(event)
    assert all(kind != "done" for kind, _ in events)
    assert response.closed


def test_sse_multiline_frames_and_heartbeats():
    event = {"type": "response.completed", "response": payload()}
    lines = [": heartbeat", "event: response.completed"]
    lines.extend("data: " + line for line in json.dumps(event, indent=2).splitlines())
    lines.append("")
    assert list(bs._responses_events(FakeResponse(lines=lines))) == [event]


def test_client_disconnect_closes_responses_socket(monkeypatch):
    response = streamed_response(payload(), {"type": "response.output_text.delta", "delta": "Ready."})
    monkeypatch.setattr(bs.requests, "post", Mock(return_value=response))
    generator = bs.call_copilot_stream([{"role": "user", "content": "Hello"}])
    assert next(generator) == ("delta", "Ready.")
    generator.close()
    assert response.closed


@pytest.mark.parametrize("streaming", [False, True])
def test_401_refresh_keeps_responses_route_and_uses_new_endpoint(monkeypatch, streaming):
    rejected = FakeResponse({"error": "expired"}, status=401)
    accepted = streamed_response()
    post = Mock(side_effect=[rejected, accepted])
    monkeypatch.setattr(bs.requests, "post", post)
    monkeypatch.setattr(bs, "get_copilot_token", Mock(side_effect=[
        ("old", "https://old.example"), ("new", "https://new.example"),
    ]))
    invalidate = Mock()
    monkeypatch.setattr(bs, "_invalidate_copilot_token", invalidate)
    messages = [{"role": "user", "content": "Hello"}]
    if streaming:
        list(bs.call_copilot_stream(messages))
    else:
        bs.call_copilot(messages)
    assert [call.args[0] for call in post.call_args_list] == [
        "https://old.example/responses", "https://new.example/responses",
    ]
    assert invalidate.call_count == 1
    assert rejected.closed and accepted.closed


@pytest.mark.parametrize("start_model", [ASTRA, "gpt-4o"])
def test_fallback_rebuilds_both_endpoint_and_request_shape(monkeypatch, start_model):
    monkeypatch.setattr(bs, "MODEL", start_model)
    chat_result = {"choices": [{"message": {"role": "assistant", "content": "Legacy."}, "finish_reason": "stop"}]}
    rejected = FakeResponse({"error": "unavailable"}, status=503)
    accepted = FakeResponse(chat_result) if start_model == ASTRA else streamed_response()
    post = Mock(side_effect=[rejected, accepted])
    monkeypatch.setattr(bs.requests, "post", post)
    result, model = bs.call_copilot([{"role": "user", "content": "Hello"}], TOOLS)
    expected_model = "gpt-4o" if start_model == ASTRA else ASTRA
    assert model == expected_model and bs.MODEL == start_model
    assert result["choices"][0]["message"]["content"]
    for call in post.call_args_list:
        body = call.kwargs["json"]
        is_responses = call.args[0].endswith("/responses")
        assert ("input" in body) == is_responses
        assert ("messages" in body) != is_responses
        assert ("function" not in body["tools"][0]) == is_responses
    assert post.call_args_list[0].kwargs["json"]["model"] == start_model


def test_existing_multichoice_chat_completions_still_merge(monkeypatch):
    monkeypatch.setattr(bs, "MODEL", "gpt-4o")
    response = FakeResponse({"choices": [
        {"message": {"role": "assistant", "content": "Checking."}, "finish_reason": "stop"},
        {"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "legacy", "type": "function", "function": {"name": "Lookup", "arguments": "{}"}},
        ]}},
    ], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})
    post = Mock(return_value=response)
    monkeypatch.setattr(bs.requests, "post", post)
    result, model = bs.call_copilot([{"role": "user", "content": "Hello"}], TOOLS)
    assert post.call_args.args[0].endswith("/chat/completions")
    assert post.call_args.kwargs["json"]["tools"] == TOOLS
    assert model == "gpt-4o" and len(result["choices"]) == 1
    assert result["choices"][0]["message"]["content"] == "Checking."
    assert result["choices"][0]["finish_reason"] == "tool_calls"
    assert result["usage"]["total_tokens"] == 3


class LookupAgent:
    name = "Lookup"

    def __init__(self):
        self.perform = Mock(return_value="42")

    def to_tool(self):
        return deepcopy(TOOLS[0])

    def system_context(self):
        return ""


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
def test_public_chat_executes_a_complete_astra_tool_cycle(monkeypatch, route):
    agent = LookupAgent()
    monkeypatch.setattr(bs, "load_agents", lambda: {"Lookup": agent})
    output = [reasoning_item(), call_item()]
    post = Mock(side_effect=[
        streamed_response(payload(output)), streamed_response(payload([text_item("The answer is 42.")])),
    ])
    monkeypatch.setattr(bs.requests, "post", post)
    response = bs.app.test_client().post(route, json={
        "user_input": "Look up the answer.", "session_id": "astra-test",
        "conversation_history": [{"role": "user", "content": "Earlier."},
                                 {"role": "assistant", "content": "Understood."}],
    })
    assert response.status_code == 200
    if route == "/chat":
        result = response.get_json()
    else:
        events = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines()
                  if line.startswith("data: ")]
        assert any(event["type"] == "agent" for event in events)
        result = events[-1]
        assert result["type"] == "done" and result["streamed"]
    assert result["response"] == "The answer is 42."
    assert result["model"] == result["requested_model"] == ASTRA
    assert result["session_id"] == "astra-test"
    agent.perform.assert_called_once_with(key="answer")
    second = post.call_args_list[1].kwargs["json"]
    assert second["input"][:4] == [
        {"role": "system", "content": "Test soul."},
        {"role": "user", "content": "Earlier."},
        {"role": "assistant", "content": "Understood."},
        {"role": "user", "content": "Look up the answer."},
    ]
    assert second["input"][4:6] == output
    assert second["input"][-1]["output"] == "42"
    assert "opaque-request-local-reasoning" not in response.get_data(as_text=True)


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
def test_tool_budget_ends_with_toolless_astra_completion(monkeypatch, route):
    agent = LookupAgent()
    monkeypatch.setattr(bs, "load_agents", lambda: {"Lookup": agent})
    responses = [streamed_response(payload([reasoning_item(), call_item(f"call_{i}")])) for i in range(3)]
    responses.append(streamed_response(payload([text_item("Finished.")])))
    post = Mock(side_effect=responses)
    monkeypatch.setattr(bs.requests, "post", post)
    response = bs.app.test_client().post(route, json={"user_input": "Look up the answer."})
    response.get_data()
    assert response.status_code == 200
    assert agent.perform.call_count == 3 and post.call_count == 4
    final = post.call_args.kwargs["json"]
    assert "tools" not in final and "tool_choice" not in final
    assert len([item for item in final["input"] if item.get("type") == "function_call_output"]) == 3
    assert "Finished." in response.get_data(as_text=True)


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
def test_truncated_calls_never_execute_or_silently_fallback(monkeypatch, route):
    agent = LookupAgent()
    monkeypatch.setattr(bs, "load_agents", lambda: {"Lookup": agent})
    response = FakeResponse(lines=sse({
        "type": "response.output_item.done", "output_index": 0, "item": call_item(),
    }))
    post = Mock(return_value=response)
    monkeypatch.setattr(bs.requests, "post", post)
    result = bs.app.test_client().post(route, json={"user_input": "Look up the answer."})
    data = result.get_data(as_text=True)
    assert "error" in data
    assert '"type": "done"' not in data
    agent.perform.assert_not_called()
    assert post.call_count == 1 and response.closed


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
def test_reused_call_ids_do_not_execute_the_agent_twice(monkeypatch, route):
    agent = LookupAgent()
    monkeypatch.setattr(bs, "load_agents", lambda: {"Lookup": agent})
    post = Mock(side_effect=[
        streamed_response(payload([call_item()])), streamed_response(payload([call_item()])),
    ])
    monkeypatch.setattr(bs.requests, "post", post)
    result = bs.app.test_client().post(route, json={"user_input": "Look up the answer."})
    assert "duplicate function call ID" in result.get_data(as_text=True)
    assert agent.perform.call_count == 1 and post.call_count == 2
