"""
Tests for `_log_api_usage` (brainstem.py) — the flight-recorder hook that
captures per-request Copilot token usage so external cost-accounting tools
(e.g. RAPP AI Dyno) can price Brainstem's spend the same way they price the
Copilot CLI/Legion.

Runs two ways:
    python3 -m pytest test_api_usage_logging.py -v
    python  test_api_usage_logging.py
"""
import brainstem as bs


def _last_event(event_type):
    matching = [e for e in bs._flight_log if e["type"] == event_type]
    assert matching, f"no {event_type!r} event recorded"
    return matching[-1]


def test_log_api_usage_records_token_counts():
    before = len(bs._flight_log)
    bs._log_api_usage(
        "chat",
        "session-123",
        "gpt-4o",
        {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    )
    assert len(bs._flight_log) == before + 1
    event = _last_event("api.usage")
    assert event["data"] == {
        "endpoint": "chat",
        "session_id": "session-123",
        "model": "gpt-4o",
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }


def test_log_api_usage_ignores_missing_usage():
    # Some models/streamed responses omit `usage` entirely — must not raise
    # and must not record a bogus event.
    before = len(bs._flight_log)
    bs._log_api_usage("chat_stream", "session-456", "claude-opus-5", None)
    assert len(bs._flight_log) == before


def test_log_api_usage_ignores_non_dict_usage():
    before = len(bs._flight_log)
    bs._log_api_usage("chat", "session-789", "gpt-4o", "not-a-dict")
    assert len(bs._flight_log) == before


if __name__ == "__main__":
    test_log_api_usage_records_token_counts()
    test_log_api_usage_ignores_missing_usage()
    test_log_api_usage_ignores_non_dict_usage()
    print("ok")
