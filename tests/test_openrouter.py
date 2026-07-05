"""OpenRouter (OpenAI-compatible) LLM client tests — no network, no Docker.

Exercises one tool-call round-trip through LLMClient: the agent's Anthropic-shaped
request is translated to the OpenAI tools format on the way out, and an OpenAI
``choices[0].message.tool_calls`` response is translated back into the
``tool_use`` content block the agent loop reads.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from api.config import Settings
from api.services.llm import EXECUTE_PYTHON_TOOL, LLMClient


def _fake_completion(tool_args: dict) -> SimpleNamespace:
    """A minimal stand-in for openai.types.chat.ChatCompletion with one tool call."""
    message = SimpleNamespace(
        content="Let me run that.",
        tool_calls=[SimpleNamespace(
            id="call_abc123",
            function=SimpleNamespace(name="execute_python", arguments=json.dumps(tool_args)),
        )],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
    )


class _FakeOpenAIClient:
    """Captures the outgoing request and returns one scripted tool call."""

    def __init__(self, tool_args: dict) -> None:
        self.captured: dict = {}
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.captured = kwargs
                return _fake_completion(tool_args)

        self.chat = SimpleNamespace(completions=_Completions())


def _openrouter_settings(**overrides) -> Settings:
    defaults = dict(
        _env_file=None,
        llm_provider="openrouter",
        openrouter_api_key="sk-or-test",
        openrouter_model="anthropic/claude-sonnet-4.6",
        openrouter_http_referer="https://example.com",
        openrouter_title="Test App",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_openrouter_single_tool_call_round_trip():
    client = LLMClient(_openrouter_settings())
    fake = _FakeOpenAIClient({"code": "save_value('x', 1)"})
    client._client = fake  # swap the real OpenAI client for the scripted one

    resp = client.create(
        system="You are a data analyst.",
        messages=[{"role": "user", "content": "compute x"}],
        tools=[EXECUTE_PYTHON_TOOL],
        tool_choice={"type": "tool", "name": "execute_python"},
    )

    # --- request went out in OpenAI format ---------------------------------
    sent = fake.captured
    assert sent["model"] == "anthropic/claude-sonnet-4.6"
    assert sent["messages"][0] == {"role": "system", "content": "You are a data analyst."}
    assert sent["tools"][0]["type"] == "function"
    assert sent["tools"][0]["function"]["name"] == "execute_python"
    assert "code" in sent["tools"][0]["function"]["parameters"]["properties"]
    assert sent["tool_choice"] == {"type": "function", "function": {"name": "execute_python"}}

    # --- response came back in the agent's Anthropic shape -----------------
    tool_use = client.tool_use_of(resp)
    assert tool_use is not None
    assert tool_use.name == "execute_python"
    assert tool_use.input == {"code": "save_value('x', 1)"}
    assert client.text_of(resp) == "Let me run that."
    assert resp.stop_reason == "tool_use"
    assert resp.usage.input_tokens == 11 and resp.usage.output_tokens == 7


def test_openrouter_client_is_wired_to_openrouter():
    """The real OpenAI client is pointed at OpenRouter with the optional headers."""
    client = LLMClient(_openrouter_settings())
    assert client.provider == "openrouter"
    assert str(client._client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"
    headers = client._client.default_headers
    assert headers["HTTP-Referer"] == "https://example.com"
    assert headers["X-Title"] == "Test App"


def test_openrouter_headers_omitted_when_unset():
    client = LLMClient(_openrouter_settings(openrouter_http_referer="", openrouter_title=""))
    headers = client._client.default_headers
    assert "HTTP-Referer" not in headers
    assert "X-Title" not in headers
