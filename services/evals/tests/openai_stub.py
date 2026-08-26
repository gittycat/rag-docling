"""A test-only OpenAI-compatible HTTP server.

Test scaffolding, never imported by the service. It exists because the thing Unit D
changes is a *transport*: whether `base_url` and `temperature` actually leave the
process, whether a JSON-schema-constrained request is shaped the way an
OpenAI-compatible server expects, and what the judge does when the server refuses
it. A mocked `acomplete` cannot answer any of those — it never serializes a request.

What this is not: evidence that a real vLLM release behaves this way. It implements
the subset of the OpenAI chat-completions contract the judge uses, and asserts on
what we send. Compatibility with an actual vLLM build needs a smoke test against a
running server, which is out of scope for a machine with no GPU.
"""

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class RecordedRequest:
    path: str
    headers: dict[str, str]
    body: dict[str, Any]

    @property
    def messages(self) -> list[dict[str, Any]]:
        return self.body.get("messages", [])

    @property
    def prompt_text(self) -> str:
        return "\n".join(str(m.get("content", "")) for m in self.messages)


@dataclass
class Reply:
    """One scripted server response."""

    content: str | None = None
    status: int = 200
    error_message: str = ""
    usage: dict[str, int] = field(
        default_factory=lambda: {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        }
    )


def json_reply(score: float, reasoning: str = "stub reasoning") -> Reply:
    return Reply(content=json.dumps({"score": score, "reasoning": reasoning}))


def text_reply(score: float, reasoning: str = "stub reasoning") -> Reply:
    return Reply(content=f"SCORE: {score}\nREASONING: {reasoning}")


def unsupported_response_format() -> Reply:
    """What an OpenAI-compatible server without guided decoding answers."""
    return Reply(
        status=400,
        error_message="response_format is not supported by this model",
    )


class OpenAICompatibleStub:
    """A localhost server speaking enough of /v1/chat/completions to drive the judge.

    Replies are consumed from a queue; the last one repeats once the queue is
    drained, so a test that only cares about request shape can queue a single
    reply. With no queue at all the stub answers in whichever format the request
    asked for, which is how a well-behaved server would act.
    """

    def __init__(self, replies: list[Reply] | None = None):
        self.replies: list[Reply] = list(replies or [])
        self.requests: list[RecordedRequest] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def __enter__(self) -> "OpenAICompatibleStub":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def start(self) -> None:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:  # silence stderr noise
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    body = {"_unparseable": raw.decode("utf-8", "replace")}

                recorded = RecordedRequest(
                    path=self.path,
                    headers={k.lower(): v for k, v in self.headers.items()},
                    body=body,
                )
                reply = stub._record_and_next(recorded, body)

                if reply.status >= 400:
                    payload = {
                        "error": {
                            "message": reply.error_message,
                            "type": "invalid_request_error",
                        }
                    }
                else:
                    payload = {
                        "id": "chatcmpl-stub",
                        "object": "chat.completion",
                        "created": 0,
                        "model": body.get("model", "stub-model"),
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": reply.content or "",
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": reply.usage,
                    }

                encoded = json.dumps(payload).encode()
                self.send_response(reply.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # Short poll interval: serve_forever's default makes every stop() wait
        # half a second, which dominates a suite of small transport tests.
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def port(self) -> int:
        assert self._server is not None, "stub not started"
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.requests)

    @property
    def last_request(self) -> RecordedRequest:
        with self._lock:
            assert self.requests, "stub received no requests"
            return self.requests[-1]

    def _record_and_next(self, recorded: RecordedRequest, body: dict[str, Any]) -> Reply:
        with self._lock:
            self.requests.append(recorded)
            if not self.replies:
                return self._echo_requested_format(body)
            if len(self.replies) == 1:
                return self.replies[0]
            return self.replies.pop(0)

    @staticmethod
    def _echo_requested_format(body: dict[str, Any]) -> Reply:
        if body.get("response_format"):
            return json_reply(0.75)
        return text_reply(0.75)
