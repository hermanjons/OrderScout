"""Loopback-only inference, exact context accounting and native function calls."""
from __future__ import annotations

import json
import queue
import threading
import time
from contextlib import nullcontext
from urllib.parse import urlsplit

import requests

from AI.processors.cloud_runtime import _extract_openai_text, _extract_openai_tool_decision, _provider_tool_definitions
from AI.processors.provider_adapters import capability_profile_from_record, guarded_json_prompt
from AI.runtime.prompt import provider_prompt_fields
from AI.runtime.response_stream import (
    ResponseStreamCancelled, ResponseStreamIncomplete, callback_for_contract,
    request_provider_stream,
)


class LocalContextExceeded(RuntimeError):
    @property
    def user_message(self):
        return str(self)


class LocalGenerationIncomplete(RuntimeError):
    @property
    def user_message(self):
        return str(self)


class LocalGenerationCancelled(RuntimeError):
    pass


def build_local_http_client(*, base_url, model, plan, record=None):
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Yerel motor yalnızca bu bilgisayara bağlanabilir.")
    # Never send localhost traffic through a configured corporate/cloud proxy.
    session = requests.Session()
    session.trust_env = False
    lock = threading.Lock()
    options = dict(record or {})
    profile = capability_profile_from_record({"provider_code": "local", "default_model": model,
        "model_metadata": {"supported_parameters": ["tools", "response_format"],
                           "context_length": plan.num_ctx}}, native_tool_runtime_enabled=True,
        structured_output_runtime_enabled=True).to_dict()

    def post(path, payload, *, timeout=30, stream_callback=None):
        def validate(response):
            if not response.ok:
                try:
                    message = response.json().get("error", {})
                    message = message.get("message") if isinstance(message, dict) else message
                except ValueError:
                    message = response.text[-1000:]
                raise RuntimeError("Yerel motor isteği tamamlanamadı: " + str(message or response.status_code)[:1000])

        if stream_callback is not None:
            stream_payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
            remaining = timeout
            deadline = getattr(client, "turn_deadline_monotonic", None)
            if isinstance(deadline, (int, float)):
                remaining = min(remaining, max(0.05, deadline - time.monotonic()))
            try:
                return request_provider_stream(
                    request=lambda: session.post(base_url.rstrip("/") + path,
                        json=stream_payload, timeout=(10, remaining), stream=True),
                    family="openai", callback=stream_callback, timeout=remaining,
                    validate_status=validate,
                    cancelled=lambda: bool(getattr(getattr(client, "task_control", None), "pause_requested", False)),
                )
            except ResponseStreamCancelled as exc:
                cancel = getattr(client, "cancel_generation", None)
                if callable(cancel):
                    cancel()
                client.resource_plan["restart_required"] = True
                raise LocalGenerationCancelled("Yerel model çalışması duraklatıldı.") from exc
            except ResponseStreamIncomplete as exc:
                raise LocalGenerationIncomplete("Yerel model yanıtı tamamlanmadı; kesilmiş araç çağrısı çalıştırılmadı.") from exc

        def request():
            return session.post(base_url.rstrip("/") + path, json=payload, timeout=(10, timeout))
        if timeout <= 30:
            response = request()
        else:
            result = queue.Queue(maxsize=1)
            def run():
                try:
                    result.put((True, request()))
                except Exception as error:
                    result.put((False, error))
            worker = threading.Thread(target=run, name="orderscout-local-inference", daemon=True)
            worker.start()
            while True:
                control = getattr(client, "task_control", None)
                if control is not None and control.pause_requested:
                    cancel = getattr(client, "cancel_generation", None)
                    if callable(cancel):
                        cancel()
                    client.resource_plan["restart_required"] = True
                    raise LocalGenerationCancelled("Yerel model çalışması duraklatıldı.")
                try:
                    ok, response = result.get(timeout=0.1)
                    if not ok:
                        raise response
                    break
                except queue.Empty:
                    continue
        validate(response)
        return response.json()

    def invoke(prompt, *, tools=None, schema=None, contract="text"):
        nonlocal base_url, plan
        wire, names = _provider_tool_definitions(tools or [], family="openai")
        messages = provider_prompt_fields(prompt)["messages"]
        effort = str(plan.reasoning_effort)
        # Template controls, not text injected into the user's task. Preserve
        # the full prompt, observation references and all selected tool schemas.
        template_kwargs = {"enable_thinking": effort in {"medium", "high"},
                           "reasoning_effort": effort if effort in {"low", "medium", "high"} else "low"}
        with lock, getattr(client, "runtime_lock", None) or nullcontext():
            if client.resource_plan.get("restart_required"):
                restart = getattr(client, "restart_runtime", None)
                if not callable(restart):
                    raise RuntimeError("Yerel modelin yeniden açılması gerekiyor.")
                base_url = restart()
                client.resource_plan["restart_required"] = False
            ensure = getattr(client, "ensure_runtime", None)
            if callable(ensure):
                base_url = ensure()
            template = {"messages": messages, "add_generation_prompt": True,
                        "chat_template_kwargs": template_kwargs}
            if wire:
                template["tools"] = wire
            rendered = post("/apply-template", template).get("prompt")
            if not isinstance(rendered, str):
                raise RuntimeError("Yerel motor gerçek bağlam boyutunu hesaplayamadı.")
            token_payload = post("/tokenize", {"content": rendered, "add_special": False})
            tokens = token_payload.get("tokens")
            if not isinstance(tokens, list):
                raise RuntimeError("Yerel motor bağlam ölçümünü döndürmedi.")
            count = len(tokens) + 1  # reserve the server's BOS token as well
            client.resource_plan.update({"prompt_tokens": count, "prompt_compacted": False,
                "context_policy": "preserve_grow_or_error", "invocation_contract": contract,
                "model_invocation_attempted": False})
            if count + plan.max_tokens + 32 > plan.num_ctx:
                resize = getattr(client, "resize_context", None)
                if callable(resize):
                    base_url, plan = resize(count + plan.max_tokens + 32)
                if count + plan.max_tokens + 32 > plan.num_ctx:
                    client.resource_plan["context_overflow"] = True
                    raise LocalContextExceeded(f"Yerel model bağlamı yetmiyor: {count} girdi + {plan.max_tokens} yanıt, "
                        f"kapasite {plan.num_ctx}. Araç keşfini daraltın veya model bağlamını artırın; içerik kesilmedi.")
            payload = {"model": model, "messages": messages, "max_tokens": plan.max_tokens,
                **dict(plan.sampling_defaults), "stream": False,
                "chat_template_kwargs": template_kwargs, "cache_prompt": True,
                "reasoning_effort": template_kwargs["reasoning_effort"]}
            for field in ("temperature", "top_p", "top_k", "repeat_penalty", "seed", "presence_penalty", "min_p"):
                if options.get(field) is not None:
                    payload[field] = options[field]
            if wire:
                payload.update({"tools": wire, "tool_choice": "auto", "parallel_tool_calls": False})
            if schema:
                payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "decision", "schema": schema}}
            client.resource_plan["model_invocation_attempted"] = True
            response = post("/v1/chat/completions", payload, timeout=plan.inference_timeout_seconds,
                            stream_callback=callback_for_contract(contract))
            client.last_response = response  # transient diagnostic; never checkpointed by the host
            choice = (response.get("choices") or [{}])[0]
            client.resource_plan.update({"usage": response.get("usage") or {}, "timings": response.get("timings") or {},
                "finish_reason": choice.get("finish_reason"), "actual_model": response.get("model") or model,
                "model_invoked": True, "fallback_used": False})
            if contract == "completion_review" and (
                (choice.get("message") or {}).get("tool_calls")
                or choice.get("finish_reason") in {"tool_calls", "function_call"}
            ):
                raise LocalGenerationIncomplete("Yanıt denetimi araç çalıştıramaz.")
            if choice.get("finish_reason") == "length":
                raise LocalGenerationIncomplete("Yerel modelin yanıt sınırı doldu; kesilmiş araç çağrısı çalıştırılmadı. Yanıt sınırını artırın.")
            answer = _extract_openai_tool_decision(response, wire_to_source=names) if wire else _extract_openai_text(response)
            if not str(answer or "").strip():
                raise LocalGenerationIncomplete("Yerel model görünür yanıt üretmedi; düşünme ve yanıt bütçesini kontrol edin.")
            return answer

    def client(prompt):
        return invoke(prompt)

    client.resource_plan = {**plan.to_dict(), "provider_code": "local", "capability_profile": profile,
        "degradation_mode": profile["degradation_mode"], "tool_menu_limit": plan.tool_menu_limit,
        "final_answer_review_enabled": True}
    client.invoke_tools = lambda prompt, *, tools: invoke(prompt, tools=tools, contract="native_tools")
    client.invoke_json_text = lambda prompt, *, schema=None: invoke(guarded_json_prompt(prompt, schema), contract="json_text_guarded")
    client.invoke_structured = lambda prompt, *, schema=None: invoke(prompt, schema=schema, contract="structured_output")
    client.invoke_completion_review = lambda prompt, *, schema: invoke(
        guarded_json_prompt(prompt, schema), schema=schema, contract="completion_review")
    client.close = session.close
    return client
