"""
Copilot HTTP keep-alive: calls share one connection pool, yet every call still sends
what a one-shot requests.post would. A call whose connection fails is never resent (the
server may already have run it): it fails exactly as a one-shot call does, and the next
call starts on a fresh pool. Hermetic: a loopback fake Copilot API counts TCP connections.

    python3 -m pytest tests/test_connection_reuse.py -v
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

import brainstem as bs

_PROXY_VARS = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy",
               "NO_PROXY", "no_proxy", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


class _FakeCopilot:
    """HTTP/1.1 keep-alive stand-in for /models and /chat/completions (JSON or SSE)."""

    def __init__(self):
        self.conns = 0
        self.requests = []          # (method, path, headers, body) per request received
        self.drop_reused = False    # hang up on a kept-alive connection's next request
        self.drop_all = False       # hang up on every request, unanswered
        self.slow = 0.0             # seconds to sit on a POST before answering
        self.hold_after_done = 0.0  # seconds between the [DONE] event and the body's end
        lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.served = 0
                with lock:
                    fake.conns += 1

            def log_message(self, *args):
                pass

            def _hang_up(self, body=None):
                fake.requests.append((self.command, self.path, dict(self.headers), body))
                if fake.drop_all or (fake.drop_reused and self.served):
                    self.close_connection = True
                    return True
                self.served += 1
                return False

            def _json(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Set-Cookie", "affinity=node-7; Path=/")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self._hang_up():
                    self._json({"data": [{"id": "gpt-4o"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self._hang_up(body):  # recorded only once fully read: the server "ran" it
                    return
                time.sleep(fake.slow)
                if not body.get("stream"):
                    self._json({"choices": [{"message": {"role": "assistant", "content": "Hello there"},
                                             "finish_reason": "stop"}]})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                events = b"".join(b"%X\r\n%s\r\n" % (len(data), data) for data in (
                    b'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n',
                    b'data: {"choices":[{"delta":{"content":"there"},"finish_reason":"stop"}]}\n\n',
                    b"data: [DONE]\n\n"))
                if fake.hold_after_done:
                    self.wfile.write(events)
                    time.sleep(fake.hold_after_done)
                    events = b""
                self.wfile.write(events + b"0\r\n\r\n")

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass  # clients hanging up on a finished or abandoned response are expected

        self.server = Server(("127.0.0.1", 0), Handler)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, path="/chat/completions"):
        return self.base + path

    def posts(self):
        return sum(1 for method, *_ in self.requests if method == "POST")


@pytest.fixture
def fake(monkeypatch):
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setattr(bs, "_copilot_http", None)
    monkeypatch.setattr(bs, "_copilot_http_used", 0.0)
    server = _FakeCopilot()
    monkeypatch.setattr(bs, "get_copilot_token", lambda: ("tok", server.base))
    yield server
    server.server.shutdown()
    server.server.server_close()


def _stream(text="hi"):
    return list(bs.call_copilot_stream([{"role": "user", "content": text}], model="gpt-4o"))


# ── Reuse ───────────────────────────────────────────────────────────────────────

def test_chat_calls_share_one_connection(fake):
    for _ in range(3):  # e.g. a turn with a tool round, then the next turn
        result, model = bs.call_copilot([{"role": "user", "content": "hi"}])
        assert result["choices"][0]["message"]["content"] == "Hello there"
    assert bs._copilot_request("GET", fake.url("/models"), timeout=10).json()["data"]
    assert fake.conns == 1 and len(fake.requests) == 4


def test_finished_streams_return_their_connection_to_the_pool(fake):
    for _ in range(3):
        events = _stream()
        assert [kind for kind, _ in events] == ["delta", "delta", "done"]
        assert events[-1][1]["message"]["content"] == "Hello there"
    bs.call_copilot([{"role": "user", "content": "hi"}])
    assert fake.conns == 1


def test_abandoned_stream_closes_its_connection_instead_of_pooling_it(fake):
    gen = bs.call_copilot_stream([{"role": "user", "content": "hi"}], model="gpt-4o")
    assert next(gen) == ("delta", "Hello ")
    gen.close()  # client disconnect mid-stream
    _stream()    # must not be handed the half-read socket
    assert fake.conns == 2


def test_stream_whose_body_never_ends_still_finishes_promptly(fake):
    fake.hold_after_done = 8  # [DONE] arrives, the chunked terminator doesn't
    started = time.monotonic()
    events = _stream()
    assert events[-1][0] == "done" and events[-1][1]["message"]["content"] == "Hello there"
    assert time.monotonic() - started < 5  # waited ~1 s for the terminator, not 8 s or the 30 s read timeout
    fake.hold_after_done = 0
    _stream()
    assert fake.conns == 2  # the unfinished connection was closed, not reused


def test_pool_idle_past_the_limit_is_replaced(fake):
    bs.call_copilot([{"role": "user", "content": "hi"}])
    bs._copilot_http_used -= bs._COPILOT_IDLE_S + 1  # e.g. a laptop that slept
    bs.call_copilot([{"role": "user", "content": "hi"}])
    assert fake.conns == 2


def test_clock_stepping_back_starts_a_fresh_pool(fake):
    bs.call_copilot([{"role": "user", "content": "hi"}])
    bs._copilot_http_used = time.time() + 3600
    bs.call_copilot([{"role": "user", "content": "hi"}])
    assert fake.conns == 2


def test_concurrent_chat_and_stream_calls_share_the_pool_safely(fake):
    errors, results = [], []

    def worker(streaming):
        try:
            for _ in range(8):
                if streaming:
                    results.append(_stream()[-1][1]["message"]["content"])
                else:
                    results.append(bs.call_copilot([{"role": "user", "content": "hi"}])[0]
                                   ["choices"][0]["message"]["content"])
        except Exception as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(i % 2 == 0,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not errors
    assert results == ["Hello there"] * 48
    assert fake.conns <= 6


# ── Same request as a one-shot call ────────────────────────────────────────────

def test_pooled_calls_send_the_one_shot_headers_and_never_cookies(fake):
    headers = {"Authorization": "Bearer tok", "Content-Type": "application/json",
               "Editor-Version": "vscode/1.95.0", "Copilot-Integration-Id": "vscode-chat"}
    requests.post(fake.url(), headers=headers, json={"model": "m"}, timeout=10)  # what Grail sends
    for _ in range(2):  # both answers carry Set-Cookie
        bs._copilot_request("POST", fake.url(), headers=headers, json={"model": "m"}, timeout=10)
    one_shot, first, second = (sent for _method, _path, sent, _body in fake.requests)
    assert first == one_shot and second == one_shot
    assert "Cookie" not in second


def test_env_proxy_applies_per_call_on_the_shared_session(fake, monkeypatch):
    bs._copilot_request("GET", fake.url("/models"), timeout=10)  # session created without a proxy
    monkeypatch.setenv("HTTP_PROXY", fake.base)                  # the fake doubles as a forward proxy
    assert bs._copilot_request("GET", "http://copilot.invalid/models", timeout=10).status_code == 200
    assert fake.requests[-1][1] == "http://copilot.invalid/models"


def test_env_ca_bundle_applies_per_call_on_the_shared_session(fake, monkeypatch):
    bs._copilot_request("GET", fake.url("/models"), timeout=10)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/nonexistent/brainstem-test-ca.pem")
    with pytest.raises(OSError, match="brainstem-test-ca.pem"):
        bs._copilot_request("GET", "https://copilot.invalid/models", timeout=10)


# ── A failed connection: never resent, reported unchanged, next call starts fresh ──

def _open_stream():
    gen = bs.call_copilot_stream([{"role": "user", "content": "hi"}], model="gpt-4o")
    assert next(gen) == ("delta", "Hello ")  # in flight, holding its own connection
    return gen


def test_lost_response_is_sent_once_and_chat_fails_exactly_as_grail_does(fake, monkeypatch):
    # The reviewer's case: the server fully reads and records the POST on the reused
    # socket, then hangs up without replying. It may already have run (and billed) the
    # generation, so it must not be sent again, and /chat must fail exactly as it does
    # when Grail's one-shot requests.post meets the same server.
    monkeypatch.setattr(bs, "load_agents", lambda: {})
    client = bs.app.test_client()
    assert client.post("/chat", json={"user_input": "hi"}).get_json()["response"] == "Hello there"
    fake.drop_all = True
    with pytest.raises(requests.exceptions.ConnectionError) as one_shot:
        requests.post(fake.url(), json={"model": "m"}, timeout=10)
    conns, seen = fake.conns, len(fake.requests)
    reply = client.post("/chat", json={"user_input": "again"})
    assert [(method, body["messages"][-1]["content"])
            for method, _path, _headers, body in fake.requests[seen:]] == [("POST", "again")]
    assert fake.conns == conns  # it went out on the pooled socket
    assert (reply.status_code, reply.get_json()) == (500, {"error": str(one_shot.value)})


@pytest.mark.parametrize("failure", ["lost on a reused socket", "lost on a new socket", "read timeout"])
def test_the_pool_never_sends_a_request_twice(fake, failure):
    if failure != "lost on a new socket":
        bs._copilot_request("POST", fake.url(), json={}, timeout=10)  # warm the pool
    if failure == "read timeout":
        fake.slow, timeout = 1.0, (5, 0.2)
    else:
        fake.drop_all, timeout = True, 10
    posts = fake.posts()
    with pytest.raises(requests.exceptions.RequestException) as pooled:
        bs._copilot_request("POST", fake.url(), json={"model": "m"}, timeout=timeout)
    assert fake.posts() == posts + 1
    with pytest.raises(requests.exceptions.RequestException) as one_shot:  # Grail, same server
        requests.post(fake.url(), json={"model": "m"}, timeout=timeout)
    assert (type(pooled.value), str(pooled.value)) == (type(one_shot.value), str(one_shot.value))


def test_after_a_failure_the_next_calls_start_on_a_fresh_pool(fake, monkeypatch):
    first, second = _open_stream(), _open_stream()
    list(first), list(second)  # both finish: the pool now holds two idle sockets
    events = []
    monkeypatch.setattr(bs, "_tlog", lambda event, data=None, level="info": events.append(event))
    fake.drop_reused = True    # every reused socket is dead now, e.g. after a network change
    with pytest.raises(requests.exceptions.ConnectionError):
        bs.call_copilot([{"role": "user", "content": "hi"}])
    assert bs._copilot_http is None
    held = _open_stream()      # two calls at once: from the old pool, one would get its other socket
    result, _model = bs.call_copilot([{"role": "user", "content": "hi"}])
    assert result["choices"][0]["message"]["content"] == "Hello there"
    assert list(held)[-1][1]["message"]["content"] == "Hello there"
    assert fake.conns == 4 and events == ["api.connection_pool_dropped"]


def test_a_late_failure_never_drops_a_newer_pool(fake, monkeypatch):
    bs._copilot_request("GET", fake.url("/models"), timeout=10)  # warm pool
    newer = requests.Session()

    def fail_after_another_call_replaced_the_pool(session, *args, **kwargs):
        bs._copilot_http = newer
        raise requests.exceptions.ConnectionError("lost")

    monkeypatch.setattr(requests.Session, "request", fail_after_another_call_replaced_the_pool)
    with pytest.raises(requests.exceptions.ConnectionError):
        bs._copilot_request("POST", fake.url(), json={}, timeout=10)
    assert bs._copilot_http is newer
