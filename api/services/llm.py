"""Claude API wrapper with the agent's tool definitions.

The agent uses native tool calling (never string-parsing of code blocks):
the single tool ``execute_python`` carries the code the model wants to run.

The agent is written against the Anthropic Messages shape (content blocks,
``tool_use``/``tool_result`` turns). To support OpenAI-compatible backends
(OpenRouter — the default — as well as Ollama, vLLM, LiteLLM, ...) without
touching the agent, ``LLMClient`` translates those backends' chat schema to and
from the Anthropic shape at the boundary: outgoing messages/tools are converted
to OpenAI format, and the OpenAI response is wrapped in lightweight objects that
duck-type an Anthropic ``Message``.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import anthropic

from api.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _repair_json(s: str) -> str:
    """Best-effort cleanup of the JSON quirks small / local models emit.

    Conservative on purpose — it only fixes patterns that are unambiguous
    outside of string values, so it can't silently corrupt good data:
      * ``//`` full-line and ``/* */`` comments
      * trailing commas before ``}`` / ``]``
      * Python literals (``None`` / ``True`` / ``False`` / ``NaN``) when they
        appear in value position (right after ``:`` ``[`` or ``,``).
    """
    s = re.sub(r'(?m)^\s*//[^\n]*$', '', s)
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.DOTALL)
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    for lit, repl in (("None", "null"), ("True", "true"), ("False", "false"),
                      ("NaN", "null"), ("Infinity", "null")):
        s = re.sub(r'([:\[,]\s*)' + lit + r'\b', r'\1' + repl, s)
    return s

EXECUTE_PYTHON_TOOL: dict[str, Any] = {
    "name": "execute_python",
    "description": (
        "Execute Python code in the isolated analysis sandbox. The code runs in a fresh process "
        "with pd/np/px/go pre-imported and DATA_DIR pointing at the session data directory. "
        "Results must be recorded with save_table(name, df), save_value(name, value) and "
        "save_chart(name, fig); stdout is captured but is NOT a result. "
        "Call this whenever any number, table or chart is needed — never compute values yourself."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "The Python code to execute."},
        },
        "required": ["code"],
    },
}


class LLMError(RuntimeError):
    """Raised when the LLM response cannot be used (e.g. malformed JSON)."""


# --- Anthropic-shaped response objects for the OpenAI-compatible path ---------
# These duck-type just enough of anthropic.types.Message for the agent and the
# LLMClient.text_of / tool_use_of helpers: content blocks with .type/.text and
# .id/.name/.input, plus .stop_reason and .usage.{input,output,cache_read}_tokens.

@dataclass
class _Block:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _Message:
    content: list[_Block]
    stop_reason: str
    usage: _Usage


class LLMClient:
    """LLM wrapper used by the agent orchestrator.

    Defaults to OpenRouter (``llm_provider == "openrouter"``) over its
    OpenAI-compatible API; ``"openai"`` targets any other OpenAI-compatible chat
    endpoint (e.g. Ollama); ``"anthropic"`` uses the native Messages API.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = (self.settings.llm_provider or "openrouter").lower()
        # The model id used for chat completions, resolved per provider.
        self._model = self.settings.active_model
        if self.provider == "openrouter":
            from openai import OpenAI  # imported lazily so the dep is optional
            # Optional headers let the app show up on OpenRouter's leaderboards;
            # only sent when configured.
            headers: dict[str, str] = {}
            if self.settings.openrouter_http_referer:
                headers["HTTP-Referer"] = self.settings.openrouter_http_referer
            if self.settings.openrouter_title:
                headers["X-Title"] = self.settings.openrouter_title
            self._client = OpenAI(
                # The SDK requires a non-empty key; real calls need OPENROUTER_API_KEY.
                api_key=self.settings.openrouter_api_key or "not-needed",
                base_url=self.settings.openrouter_base_url or "https://openrouter.ai/api/v1",
                default_headers=headers or None,
                # The SDK retries 429s and connection errors up to this many times.
                max_retries=3,
            )
        elif self.provider == "openai":
            from openai import OpenAI  # imported lazily so the dep is optional
            self._client = OpenAI(
                # Ollama ignores the key but the SDK requires a non-empty value.
                api_key=self.settings.openai_api_key or "not-needed",
                base_url=self.settings.openai_base_url or None,
                max_retries=3,
            )
        else:
            # auth_token (Bearer) and api_key (x-api-key) are mutually exclusive:
            # the API rejects requests carrying both headers.
            auth_token = self.settings.anthropic_auth_token or None
            self._client = anthropic.Anthropic(
                api_key=None if auth_token else (self.settings.anthropic_api_key or None),
                auth_token=auth_token,
                base_url=self.settings.anthropic_base_url or None,
                max_retries=3,
            )

    def create(self, *, system: str, messages: list[dict[str, Any]],
               tools: list[dict[str, Any]] | None = None,
               tool_choice: dict[str, Any] | None = None) -> Any:
        if self.provider in ("openrouter", "openai"):
            return self._create_openai(system, messages, tools, tool_choice)
        return self._create_anthropic(system, messages, tools, tool_choice)

    def _call_with_retry(self, fn: Any, *, attempts: int = 5) -> Any:
        """Run an API call, riding out transient 429s (common on OpenRouter's
        free tier). Honours the provider's ``Retry-After`` header when present,
        otherwise backs off exponentially. Non-429 errors surface immediately.
        """
        delay = 6.0
        for i in range(attempts):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 — inspect status, re-raise if not 429
                resp = getattr(exc, "response", None)
                status = getattr(exc, "status_code", None) or getattr(resp, "status_code", None)
                is_429 = status == 429 or "429" in str(exc) or "rate-limit" in str(exc).lower()
                if not is_429 or i == attempts - 1:
                    raise
                wait = delay
                try:
                    ra = resp.headers.get("retry-after") if resp is not None else None
                    if ra is not None:
                        wait = float(ra)
                except (TypeError, ValueError, AttributeError):
                    pass
                wait = min(max(wait, 2.0), 40.0)
                logger.warning("rate-limited (429); retry %d/%d in %.0fs", i + 1, attempts - 1, wait)
                time.sleep(wait)
                delay = min(delay * 1.7, 40.0)

    def _create_anthropic(self, system: str, messages: list[dict[str, Any]],
                          tools: list[dict[str, Any]] | None,
                          tool_choice: dict[str, Any] | None) -> anthropic.types.Message:
        kwargs: dict[str, Any] = {
            "model": self.settings.anthropic_model,
            "max_tokens": self.settings.llm_max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        response = self._call_with_retry(lambda: self._client.messages.create(**kwargs))
        logger.info(
            "llm call stop=%s in=%s out=%s cached=%s",
            response.stop_reason, response.usage.input_tokens,
            response.usage.output_tokens, response.usage.cache_read_input_tokens,
        )
        return response

    def _create_openai(self, system: str, messages: list[dict[str, Any]],
                       tools: list[dict[str, Any]] | None,
                       tool_choice: dict[str, Any] | None) -> _Message:
        oai_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        oai_messages.extend(_to_openai_messages(messages))
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self.settings.llm_max_tokens,
            "messages": oai_messages,
        }
        if tools:
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]
        if tool_choice:
            kwargs["tool_choice"] = _to_openai_tool_choice(tool_choice)
        completion = self._call_with_retry(lambda: self._client.chat.completions.create(**kwargs))
        response = _from_openai_completion(completion)
        logger.info(
            "llm call (%s) stop=%s in=%s out=%s",
            self.provider, response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens,
        )
        return response

    @staticmethod
    def text_of(response: Any) -> str:
        return "".join(b.text for b in response.content if b.type == "text")

    @staticmethod
    def tool_use_of(response: Any) -> Any | None:
        for block in response.content:
            if block.type == "tool_use":
                return block
        return None

    @staticmethod
    def parse_json(text: str) -> Any:
        """Parse a JSON object out of model text, tolerating code fences."""
        cleaned = text.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
        if fence:
            cleaned = fence.group(1)
        # narrow to the outermost {...} so any prose around it is dropped
        start, end = cleaned.find("{"), cleaned.rfind("}")
        candidate = cleaned[start:end + 1] if start != -1 and end > start else cleaned
        # strict=False tolerates literal control characters (raw newlines/tabs)
        # inside strings — a common quirk of smaller / local models.
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError as first:
            last = first
        logger.warning("malformed JSON from model (%s); attempting repair. raw=%.1200s",
                       last, candidate)
        try:
            return json.loads(_repair_json(candidate), strict=False)
        except json.JSONDecodeError as exc:
            last = exc
        raise LLMError(f"model returned malformed JSON: {last}") from last


# --- Anthropic <-> OpenAI translation (used only by the OpenAI provider path) -

def _block_to_dict(block: Any) -> dict[str, Any]:
    """Normalise a content block (dict or _Block/anthropic block) to a dict."""
    if isinstance(block, dict):
        return block
    out: dict[str, Any] = {"type": block.type}
    if block.type == "text":
        out["text"] = block.text or ""
    elif block.type == "tool_use":
        out["id"] = block.id
        out["name"] = block.name
        out["input"] = block.input or {}
    return out


def _stringify_tool_result(content: Any) -> str:
    """tool_result content is normally a string, but tolerate block lists."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            b = _block_to_dict(block)
            parts.append(b.get("text", "") if b.get("type") == "text" else json.dumps(b))
        return "\n".join(parts)
    return str(content)


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-format turns to OpenAI chat messages.

    Handles the shapes the agent produces: string content, assistant turns with
    text + tool_use blocks, and user turns carrying tool_result blocks.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        for block in content:
            b = _block_to_dict(block)
            btype = b.get("type")
            if btype == "text":
                text_parts.append(b.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": b.get("id") or f"call_{uuid4().hex[:8]}",
                    "type": "function",
                    "function": {"name": b.get("name", ""),
                                 "arguments": json.dumps(b.get("input") or {})},
                })
            elif btype == "tool_result":
                tool_results.append(b)

        joined = "\n".join(t for t in text_parts if t)
        if role == "assistant":
            # Some OpenAI-compatible servers (Ollama) reject a null content even
            # when tool_calls are present, so always send a string.
            assistant: dict[str, Any] = {"role": "assistant", "content": joined}
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            out.append(assistant)
        else:  # user
            if joined:
                out.append({"role": "user", "content": joined})
            for tr in tool_results:
                out.append({
                    "role": "tool",
                    "tool_call_id": tr.get("tool_use_id"),
                    "content": _stringify_tool_result(tr.get("content", "")),
                })
    return out


def _to_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def _to_openai_tool_choice(tool_choice: dict[str, Any]) -> Any:
    kind = tool_choice.get("type")
    if kind == "tool":
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    if kind == "any":
        return "required"
    if kind == "auto":
        return "auto"
    return tool_choice


_FINISH_TO_STOP = {
    "tool_calls": "tool_use",
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "end_turn",
}


def _from_openai_completion(completion: Any) -> _Message:
    choice = completion.choices[0]
    message = choice.message
    blocks: list[_Block] = []
    if message.content:
        blocks.append(_Block(type="text", text=message.content))
    for call in (message.tool_calls or []):
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            logger.warning("tool call arguments were not valid JSON: %r", call.function.arguments)
            args = {}
        blocks.append(_Block(type="tool_use", id=call.id or f"call_{uuid4().hex[:8]}",
                             name=call.function.name, input=args))

    usage = getattr(completion, "usage", None)
    return _Message(
        content=blocks,
        stop_reason=_FINISH_TO_STOP.get(choice.finish_reason, "end_turn"),
        usage=_Usage(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        ),
    )
