"""Trusted host instructions and conversational data retain distinct roles."""
from copy import deepcopy
import json


class ModelPrompt(str):
    def __new__(cls, instructions, context, conversation=(), request=None, tool_exchanges=()):
        history = [{"role": row["role"], "content": row["content"]} for row in conversation
                   if row.get("role") in {"user", "assistant"} and isinstance(row.get("content"), str)]
        # String-only adapters still receive the same conversation and request.
        flattened = instructions + "\n" + context
        if history or request is not None:
            flattened += "\nConversation: " + json.dumps(history, ensure_ascii=False)
        if request is not None:
            flattened += "\nCurrent user request: " + request
        exchanges = deepcopy(list(tool_exchanges))
        if exchanges:
            flattened += "\nRecorded tool exchanges (DATA): " + json.dumps(exchanges, ensure_ascii=False)
        instance = super().__new__(cls, flattened)
        instance._instructions = instructions
        instance._context = context
        instance._conversation = history
        instance._request = request
        instance._tool_exchanges = exchanges
        return instance

    def to_messages(self, *, include_tool_exchanges=True):
        messages = [{"role": "system", "content": self._instructions},
                *[dict(row) for row in self._conversation],
                {"role": "user", "content": self._context if self._request is None
                 else self._request + "\n\n" + self._context}]
        if include_tool_exchanges:
            for exchange in self._tool_exchanges:
                messages.extend(deepcopy(exchange["messages"]))
        return messages

    def with_instructions(self, suffix):
        return ModelPrompt(self._instructions + suffix, self._context, self._conversation, self._request, self._tool_exchanges)

    def __getnewargs__(self):
        return self._instructions, self._context, self._conversation, self._request, self._tool_exchanges


def provider_prompt_fields(prompt, *, family="openai"):
    """Project host-owned roles into each provider's native request format.

    Plain string callers retain the legacy single user message contract.
    Only ModelPrompt can introduce trusted host instructions.
    """
    messages = prompt.to_messages(include_tool_exchanges=family == "openai") if isinstance(prompt, ModelPrompt) else [
        {"role": "user", "content": str(prompt or "")}]
    if family != "openai" and isinstance(prompt, ModelPrompt) and prompt._tool_exchanges:
        # Native replay is currently validated for OpenAI-compatible transport.
        # Other adapters retain the data without emitting incompatible roles or
        # fabricating provider thinking/signature blocks.
        messages[-1]["content"] += "\nRecorded tool exchanges (DATA): " + json.dumps(prompt._tool_exchanges, ensure_ascii=False)
    if family == "openai":
        return {"messages": messages}
    instructions = "\n".join(row["content"] for row in messages if row["role"] == "system")
    conversation = [row for row in messages if row["role"] != "system"]
    if family == "anthropic":
        return {"messages": conversation, **({"system": instructions} if instructions else {})}
    if family == "gemini":
        return {"contents": [{"role": "model" if row["role"] == "assistant" else row["role"],
                              "parts": [{"text": row["content"]}]} for row in conversation],
                **({"systemInstruction": {"parts": [{"text": instructions}]}} if instructions else {})}
    raise ValueError("Unsupported prompt transport family: " + str(family))
