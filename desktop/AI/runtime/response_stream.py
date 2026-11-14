"""Request-scoped visible text events and incremental provider SSE assembly.

The observer is captured by the request owner before starting its transport
thread. Only provider text reaches it; reasoning and function arguments remain
inside the response assembled for the existing provider extractors.
"""
from __future__ import annotations

import codecs
from contextlib import contextmanager
from contextvars import ContextVar
import json
import queue
import threading
import time
from typing import Any, Callable, Iterator
from uuid import uuid4

import requests

StreamCallback = Callable[[dict[str, str]], None]
_callback: ContextVar[StreamCallback | None] = ContextVar("provider_response_stream", default=None)


@contextmanager
def response_stream(callback: StreamCallback | None):
    token = _callback.set(callback if callable(callback) else None)
    try:
        yield
    finally:
        _callback.reset(token)


def current_response_stream_callback() -> StreamCallback | None:
    return _callback.get()


def callback_for_contract(contract: str) -> StreamCallback | None:
    return _callback.get() if contract in {"text", "final_text", "native_tools", "completion_review"} else None


class ResponseStreamCancelled(RuntimeError):
    """Human task control stopped a provider attempt; never a retry signal."""


class ResponseStreamIncomplete(requests.RequestException):
    """A failed provider response, with value-free evidence for bounded recovery.

    This belongs to the provider request error path. A plain RuntimeError used
    to skip its retry and invocation ledger, leaving only a generic UI error.
    Neither the exception nor its persisted diagnostic contains partial text
    or tool arguments.
    """

    provider_response_incomplete = True

    def __init__(self, message: str, *, reason: str = "invalid_response", finish_reason: str = ""):
        super().__init__(message)
        self.reason = reason
        self.finish_reason = finish_reason


def provider_usage_snapshot(payload: dict[str, Any], *, family: str) -> dict[str, Any]:
    """Copy accounting fields only; failed response content has no authority."""
    usage_key = "usageMetadata" if family == "gemini" else "usage"
    usage = payload.get(usage_key)
    usage = usage if isinstance(usage, dict) else {}
    keys = {
        "gemini": ("promptTokenCount", "candidatesTokenCount", "cachedContentTokenCount", "thoughtsTokenCount", "totalTokenCount"),
        "anthropic": ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"),
    }.get(family, ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens", "total_tokens", "cost"))

    def numeric_fields(value, names):
        return {key: value[key] for key in names
                if isinstance(value.get(key), (int, float)) and not isinstance(value[key], bool) and value[key] >= 0}

    safe_usage = numeric_fields(usage, keys)
    if family == "openai":
        for key, names in (("prompt_tokens_details", ("cached_tokens",)),
                           ("completion_tokens_details", ("reasoning_tokens",))):
            details = usage.get(key)
            if isinstance(details, dict):
                safe_usage[key] = numeric_fields(details, names)
    result = {usage_key: safe_usage}
    if isinstance(payload.get("model"), str):
        result["model"] = payload["model"][:200]
    return result


def iter_sse(response: Any) -> Iterator[tuple[str, str]]:
    """Decode UTF-8 and SSE framing without buffering a whole response/token batch."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    line = ""
    data: list[str] = []
    event = ""
    after_cr = False
    beginning = True

    def accept_line(value: str):
        nonlocal event, data
        if not value:
            result = (event, "\n".join(data)) if data else None
            event, data = "", []
            return result
        if value.startswith(":"):
            return None
        field, _, value = value.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            data.append(value)
        elif field == "event":
            event = value
        return None

    # One-byte reads also work with servers that do not use HTTP chunk framing;
    # a larger read size can hold short deltas until its buffer fills.
    for chunk in response.iter_content(chunk_size=1):
        if not chunk:
            continue
        text = decoder.decode(chunk) if isinstance(chunk, bytes) else str(chunk)
        for char in text:
            if beginning:
                beginning = False
                if char == "\ufeff":
                    continue
            if after_cr and char == "\n":
                after_cr = False
                continue
            after_cr = char == "\r"
            if char in "\r\n":
                frame = accept_line(line)
                line = ""
                if frame is not None:
                    yield frame
            else:
                line += char
    tail = decoder.decode(b"", final=True)
    line += tail
    # SSE dispatch requires an empty line. An unterminated last frame is not
    # promoted to a finished response when the connection is cut.


class _VisibleText:
    """Hide inline thinking tags without interpreting provider text as authority."""
    def __init__(self, emit: Callable[[str], None]):
        self.emit = emit
        self.pending = ""
        self.hidden = False

    def _visible(self, text: str):
        if text:
            self.emit(text)

    def feed(self, text: str):
        self.pending += text
        while self.pending:
            markers = ("</think>", "</analysis>") if self.hidden else ("<think>", "<analysis>")
            positions = [(self.pending.find(marker), marker) for marker in markers]
            positions = [(pos, marker) for pos, marker in positions if pos >= 0]
            if positions:
                pos, marker = min(positions)
                if not self.hidden:
                    self._visible(self.pending[:pos])
                self.pending = self.pending[pos + len(marker):]
                self.hidden = not self.hidden
                continue
            keep = max((size for marker in markers for size in range(1, len(marker))
                        if self.pending.endswith(marker[:size])), default=0)
            ready = self.pending[:-keep] if keep else self.pending
            self.pending = self.pending[-keep:] if keep else ""
            if not self.hidden:
                self._visible(ready)
            break


def _stream_error(payload: dict[str, Any], response: Any) -> requests.HTTPError:
    error = payload.get("error") or {}
    code = error.get("code") if isinstance(error, dict) else None
    kind = error.get("type") if isinstance(error, dict) else ""
    status = int(code) if str(code).isdigit() and 400 <= int(code) <= 599 else {
        "overloaded_error": 529, "rate_limit_error": 429,
        "authentication_error": 401, "permission_error": 403,
    }.get(kind, 502)
    evidence = requests.Response()
    evidence.status_code = status
    evidence.url = getattr(response, "url", "")
    evidence.headers.update(getattr(response, "headers", {}) or {})
    evidence._content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return requests.HTTPError("Provider stream returned an error event.", response=evidence)


class _Assembler:
    def __init__(self, family: str, visible: _VisibleText):
        self.family, self.visible = family, visible
        self.payload: dict[str, Any] = {}
        self.message: dict[str, Any] = {"role": "assistant", "content": ""}
        self.tools: dict[int, dict[str, Any]] = {}
        self.blocks: dict[int, dict[str, Any]] = {}
        self.block_arguments: dict[int, str] = {}
        self.open_blocks: set[int] = set()
        self.finish = ""
        self.done = False

    def feed(self, event: str, frame: dict[str, Any]):
        if self.family == "anthropic":
            self._anthropic(event, frame)
        elif self.family == "gemini":
            self._gemini(frame)
        else:
            self._openai(frame)

    def _openai(self, frame):
        for key in ("id", "model", "created", "system_fingerprint", "usage", "timings"):
            if key in frame:
                self.payload[key] = frame[key]
        for choice in frame.get("choices") or []:
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                continue
            if choice.get("finish_reason"):
                self.finish = choice["finish_reason"]
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content
                                  if isinstance(part, dict) and part.get("type", "text") in {"text", "output_text"})
            if isinstance(content, str):
                self.message["content"] += content
                self.visible.feed(content)
            for part in delta.get("tool_calls") or []:
                index = int(part.get("index", 0))
                target = self.tools.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if part.get("id"):
                    target["id"] += part["id"]
                function = part.get("function") or {}
                for key in ("name", "arguments"):
                    if isinstance(function.get(key), str):
                        target["function"][key] += function[key]

    def _anthropic(self, event, frame):
        kind = frame.get("type") or event
        if kind == "message_start":
            self.payload.update(frame.get("message") or {})
        elif kind == "content_block_start":
            index = int(frame.get("index", 0))
            self.blocks[index] = dict(frame.get("content_block") or {})
            self.open_blocks.add(index)
            if self.blocks[index].get("type") == "text":
                self.visible.feed(self.blocks[index].get("text") or "")
        elif kind == "content_block_delta":
            index = int(frame.get("index", 0))
            block, delta = self.blocks.get(index, {}), frame.get("delta") or {}
            if delta.get("type") == "text_delta" and block.get("type") == "text":
                text = delta.get("text") or ""
                block["text"] = block.get("text", "") + text
                self.visible.feed(text)
            elif delta.get("type") == "input_json_delta" and block.get("type") == "tool_use":
                self.block_arguments[index] = self.block_arguments.get(index, "") + (delta.get("partial_json") or "")
        elif kind == "content_block_stop":
            self.open_blocks.discard(int(frame.get("index", 0)))
        elif kind == "message_delta":
            self.payload.update(frame.get("delta") or {})
            self.payload.setdefault("usage", {}).update(frame.get("usage") or {})
            self.finish = self.payload.get("stop_reason") or self.finish
        elif kind == "message_stop":
            self.done = True

    def _gemini(self, frame):
        for key, value in frame.items():
            if key != "candidates":
                self.payload[key] = value
        for candidate in frame.get("candidates") or []:
            if candidate.get("index", 0) != 0:
                continue
            self.finish = candidate.get("finishReason") or self.finish
            target = self.payload.setdefault("candidates", [{"content": {"role": "model", "parts": []}}])[0]
            target.update({key: value for key, value in candidate.items() if key != "content"})
            parts = target["content"]["parts"]
            for part in (candidate.get("content") or {}).get("parts") or []:
                if isinstance(part.get("text"), str) and not part.get("thought"):
                    text = part["text"]
                    if parts and "text" in parts[-1] and not parts[-1].get("thought"):
                        parts[-1]["text"] += text
                    else:
                        parts.append(dict(part))
                    self.visible.feed(text)
                else:
                    parts.append(dict(part))

    def result(self):
        if self.family == "anthropic":
            complete = self.done and not self.open_blocks and bool(self.finish)
            bad_finish = self.finish in {"max_tokens", "model_context_window_exceeded"}
            if bad_finish:
                raise ResponseStreamIncomplete("Provider response exceeded its output limit.",
                                               reason="output_limit", finish_reason=self.finish)
            for index, arguments in self.block_arguments.items():
                try:
                    parsed = json.loads(arguments)
                except (TypeError, ValueError) as exc:
                    raise ResponseStreamIncomplete("Provider stream contained incomplete tool arguments.", reason="tool_arguments") from exc
                if not isinstance(parsed, dict):
                    raise ResponseStreamIncomplete("Provider stream tool arguments must be an object.", reason="tool_arguments")
                self.blocks[index]["input"] = parsed
            self.payload["content"] = [self.blocks[index] for index in sorted(self.blocks)]
        elif self.family == "gemini":
            complete = bool(self.finish)
            bad_finish = self.finish != "STOP"
        else:
            # The choice's native terminal reason proves generation finished.
            # Some compatible routes close cleanly after it without [DONE].
            # Continue reading until EOF/DONE so a later usage frame is retained.
            complete = bool(self.finish)
            bad_finish = self.finish not in {"stop", "tool_calls", "function_call"}
            if self.finish == "length":
                raise ResponseStreamIncomplete("Provider response exceeded its output limit.",
                                               reason="output_limit", finish_reason=self.finish)
            if self.tools:
                self.message["tool_calls"] = [self.tools[index] for index in sorted(self.tools)]
                for tool in self.tools.values():
                    try:
                        args = json.loads(tool["function"]["arguments"])
                    except (TypeError, ValueError) as exc:
                        raise ResponseStreamIncomplete("Provider stream contained incomplete tool arguments.", reason="tool_arguments") from exc
                    if not isinstance(args, dict) or not tool["function"]["name"]:
                        raise ResponseStreamIncomplete("Provider stream contained an invalid tool call.", reason="tool_arguments")
            self.payload["choices"] = [{"index": 0, "message": self.message, "finish_reason": self.finish}]
        if not complete or bad_finish:
            reason = "output_limit" if self.finish == "MAX_TOKENS" else "provider_finish" if self.finish else "connection_closed"
            raise ResponseStreamIncomplete("Provider stream did not finish completely: " + str(self.finish or "connection_closed"),
                                           reason=reason, finish_reason=self.finish)
        return self.payload

    def diagnostic(self, reason: str):
        known_finishes = {"stop", "tool_calls", "function_call", "length", "content_filter", "error",
                          "end_turn", "tool_use", "max_tokens", "model_context_window_exceeded", "stop_sequence",
                          "STOP", "MAX_TOKENS", "SAFETY", "RECITATION", "OTHER", "MALFORMED_FUNCTION_CALL"}
        return {"provider_family": self.family, "reason": reason,
                "finish_reason": self.finish if self.finish in known_finishes else "unknown" if self.finish else "",
                "terminal_received": bool(self.finish), "done_received": self.done,
                "content_characters": len(self.message["content"]),
                "tool_call_count": len(self.tools)}


def read_provider_stream(response: Any, *, family: str, emit: Callable[[str], None],
                         stopped: threading.Event | None = None,
                         accounting: Callable[[dict[str, Any], dict[str, Any]], None] | None = None) -> dict[str, Any]:
    def visible(text):
        # Capture accounting before the view can request a pause in response
        # to this delta. The owner may return before this worker runs again.
        if accounting is not None:
            accounting(provider_usage_snapshot(assembler.payload, family=family), assembler.diagnostic(""))
        emit(text)

    assembler = _Assembler(family, _VisibleText(visible))
    try:
        for event, data in iter_sse(response):
            if stopped is not None and stopped.is_set():
                raise ResponseStreamCancelled("Provider stream stopped.")
            if data.strip() == "[DONE]":
                assembler.done = True
                break
            try:
                frame = json.loads(data)
            except (TypeError, ValueError) as exc:
                raise ResponseStreamIncomplete("Provider stream contained an invalid SSE data frame.", reason="invalid_frame") from exc
            if not isinstance(frame, dict):
                raise ResponseStreamIncomplete("Provider stream contained an invalid response frame.", reason="invalid_frame")
            if frame.get("error") or event == "error" or frame.get("type") == "error":
                raise _stream_error(frame, response)
            assembler.feed(event, frame)
            if accounting is not None:
                accounting(provider_usage_snapshot(assembler.payload, family=family), assembler.diagnostic(""))
        return assembler.result()
    except Exception as exc:
        if (isinstance(exc, (requests.ConnectionError, requests.exceptions.ChunkedEncodingError, requests.exceptions.ReadTimeout))
                and not (stopped is not None and stopped.is_set()) and assembler.finish):
            # A transport EOF while reading the optional accounting trailer
            # cannot invalidate a fully terminated and validated generation.
            # Error events and malformed trailing data never enter this path.
            try:
                result = assembler.result()
            except ResponseStreamIncomplete:
                pass
            else:
                result["_provider_stream_note"] = {**assembler.diagnostic("accounting_trailer_interrupted"),
                                                    "interrupt_type": type(exc).__name__}
                return result
        reason = getattr(exc, "reason", "cancelled" if isinstance(exc, ResponseStreamCancelled) else "transport_error")
        exc.provider_stream_usage = provider_usage_snapshot(assembler.payload, family=family)
        exc.provider_stream_diagnostic = assembler.diagnostic(reason)
        raise


def request_provider_stream(*, request: Callable[[], Any], family: str,
                            callback: StreamCallback, timeout: float,
                            validate_status: Callable[[Any], None],
                            cancelled: Callable[[], bool] | None = None,
                            timeout_error: Callable[[], Exception] | None = None) -> dict[str, Any]:
    """Bound headers and the entire SSE body with one cancellable deadline."""
    stream_id = uuid4().hex
    event_lock = threading.RLock()
    stopped = threading.Event()
    results: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
    response_holder: list[Any] = []
    latest_accounting: dict[str, Any] = {}
    latest_diagnostic: dict[str, Any] = {}
    terminal = False
    deadline = time.monotonic() + max(0.05, float(timeout))

    def send(event: str, text: str = ""):
        nonlocal terminal
        with event_lock:
            if terminal:
                return
            if event in {"end", "error", "cancelled"}:
                terminal = True
            payload = {"event": event, "stream_id": stream_id}
            if event == "delta":
                payload["text"] = text
            try:
                callback(payload)
            except Exception:
                pass  # A view observer cannot change provider/tool authority.

    def close_response():
        if response_holder:
            close = getattr(response_holder[0], "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def capture_accounting(usage, diagnostic):
        with event_lock:
            if not terminal and not stopped.is_set():
                latest_accounting.clear()
                latest_accounting.update(usage)
                latest_diagnostic.clear()
                latest_diagnostic.update(diagnostic)

    def run():
        try:
            response = request()
            response_holder.append(response)
            if stopped.is_set():
                return
            validate_status(response)
            value = read_provider_stream(response, family=family,
                emit=lambda text: send("delta", text), stopped=stopped,
                accounting=capture_accounting)
            results.put((True, value))
        except Exception as exc:
            results.put((False, exc))
        finally:
            close_response()

    # An already requested pause must not open another provider request.
    if cancelled is not None and cancelled():
        raise ResponseStreamCancelled("Provider generation paused by task control.")
    send("start")
    worker = threading.Thread(target=run, name="orderscout-provider-stream", daemon=True)
    worker.start()
    try:
        while True:
            if cancelled is not None and cancelled():
                raise ResponseStreamCancelled("Provider generation paused by task control.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise timeout_error() if timeout_error else requests.Timeout("Provider stream exceeded its wall-clock budget.")
            try:
                succeeded, value = results.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            if cancelled is not None and cancelled():
                raise ResponseStreamCancelled("Provider generation paused by task control.")
            if time.monotonic() >= deadline:
                raise timeout_error() if timeout_error else requests.Timeout("Provider stream exceeded its wall-clock budget.")
            if not succeeded:
                raise value
            send("end")
            return value
    except Exception as exc:
        stopped.set()
        with event_lock:
            if not hasattr(exc, "provider_stream_usage") and latest_accounting:
                exc.provider_stream_usage = dict(latest_accounting)
                reason = "cancelled" if isinstance(exc, ResponseStreamCancelled) else "transport_error"
                exc.provider_stream_diagnostic = {**latest_diagnostic, "reason": reason}
        send("cancelled" if isinstance(exc, ResponseStreamCancelled) else "error")
        # Closing an active socket can wait on a concurrent read lock. Keep
        # that cleanup off the owner thread so its hard deadline stays true.
        threading.Thread(target=close_response, name="orderscout-stream-close", daemon=True).start()
        raise
