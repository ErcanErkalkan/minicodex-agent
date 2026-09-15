"""Model provider wrapper with structured-output, local endpoints, and retry support."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .action_schema import ACTION_SPECS, MODEL_ACTION_JSON_SCHEMA
from .model_pricing import resolve_model_price
from .prompts import SYSTEM_PROMPT
from .provider_registry import OPENAI_COMPATIBLE_PROVIDERS, get_provider_info
from .utils import extract_json, truncate


@dataclass
class ModelUsage:
    """Best-effort token/cost and action-schema accounting for provider responses."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    native_tool_calls: int = 0
    json_text_actions: int = 0
    action_validation_successes: int = 0
    action_validation_failures: int = 0
    repair_prompts: int = 0

    @property
    def schema_reliability(self) -> float:
        total = self.action_validation_successes + self.action_validation_failures
        if total == 0:
            return 0.0
        return self.action_validation_successes / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "native_tool_calls": self.native_tool_calls,
            "json_text_actions": self.json_text_actions,
            "action_validation_successes": self.action_validation_successes,
            "action_validation_failures": self.action_validation_failures,
            "repair_prompts": self.repair_prompts,
            "schema_reliability": self.schema_reliability,
        }


class ModelBudgetExceeded(RuntimeError):
    """Raised when configured model call/token/cost budget is exceeded."""


class ModelCallError(RuntimeError):
    """Raised when a model provider call fails after retry attempts."""


class ModelOutputParseError(ValueError):
    """Raised when provider text cannot be parsed as a JSON action."""

    def __init__(self, message: str, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


def _first_choice(response: Any) -> Any | None:
    choices = getattr(response, "choices", None)
    if choices:
        return choices[0]
    if isinstance(response, dict):
        choices = response.get("choices")
        if choices:
            return choices[0]
    return None


def _message_content(choice: Any) -> str:
    message = (
        choice.get("message") if isinstance(choice, dict) else getattr(choice, "message", None)
    )
    if message is None:
        return ""
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    pieces.append(text)
            else:
                text = getattr(part, "text", None) or getattr(part, "content", None)
                if isinstance(text, str):
                    pieces.append(text)
        return "\n".join(pieces)
    return "" if content is None else str(content)


def _delta_content(choice: Any) -> str:
    delta = choice.get("delta") if isinstance(choice, dict) else getattr(choice, "delta", None)
    if delta is None:
        return ""
    if isinstance(delta, dict):
        content = delta.get("content")
    else:
        content = getattr(delta, "content", None)
    return content if isinstance(content, str) else ""


def _collect_stream_text(
    events: Iterable[Any], stream_callback: Callable[[str], None] | None = None
) -> str:
    """Collect best-effort text or native tool_call arguments from streamed events."""

    pieces: list[str] = []
    final_response: Any | None = None
    streamed_tool_calls: dict[int, dict[str, str]] = {}
    for event in events:
        event_type = getattr(event, "type", "")
        if isinstance(event, dict):
            event_type = str(event.get("type", ""))
        if event_type == "response.output_text.delta":
            delta = event.get("delta") if isinstance(event, dict) else getattr(event, "delta", None)
            if isinstance(delta, str):
                pieces.append(delta)
                if stream_callback:
                    stream_callback(delta)
            continue
        if event_type == "response.completed":
            final_response = (
                event.get("response")
                if isinstance(event, dict)
                else getattr(event, "response", None)
            )
            continue
        choice = _first_choice(event)
        if choice is not None:
            delta_obj = (
                choice.get("delta") if isinstance(choice, dict) else getattr(choice, "delta", None)
            )
            tool_calls = _get_field(delta_obj, "tool_calls", []) if delta_obj is not None else []
            for tool_call in tool_calls or []:
                idx = int(_get_field(tool_call, "index", 0) or 0)
                entry = streamed_tool_calls.setdefault(idx, {"name": "", "arguments": ""})
                function = _tool_call_function(tool_call)
                name = _get_field(function, "name", "") if function is not None else ""
                arguments = _get_field(function, "arguments", "") if function is not None else ""
                if name:
                    entry["name"] = str(name)
                if isinstance(arguments, str) and arguments:
                    entry["arguments"] += arguments
                    if stream_callback:
                        stream_callback(arguments)
            delta = _delta_content(choice)
            if delta:
                pieces.append(delta)
                if stream_callback:
                    stream_callback(delta)
    if streamed_tool_calls:
        first = streamed_tool_calls[sorted(streamed_tool_calls)[0]]
        try:
            streamed_args = json.loads(first.get("arguments") or "{}")
        except json.JSONDecodeError:
            streamed_args = {"_raw_arguments": first.get("arguments", "")}
        return json.dumps(
            {
                "thought": "Native streamed Chat Completions tool_call returned by provider.",
                "action": first.get("name", ""),
                "args": streamed_args
                if isinstance(streamed_args, dict)
                else {"value": streamed_args},
            },
            ensure_ascii=False,
        )
    if pieces:
        return "".join(pieces)
    if final_response is not None:
        return response_to_text(final_response, stream_callback=stream_callback)
    return ""


def response_to_text(response: Any, stream_callback: Callable[[str], None] | None = None) -> str:
    """Extract text from OpenAI Responses API, Chat Completions, or compatible results."""

    if isinstance(response, str):
        return response

    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)
    if isinstance(response, dict) and response.get("output_text"):
        return str(response["output_text"])

    choice = _first_choice(response)
    if choice is not None:
        native_action = tool_calls_to_action_text(choice)
        if native_action:
            return native_action
        content = _message_content(choice)
        if content:
            return content

    output = getattr(response, "output", None)
    if output is None and isinstance(response, dict):
        output = response.get("output")
    if output:
        pieces: list[str] = []
        for item in output:
            content = (
                item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            )
            if content:
                for part in content:
                    text = (
                        part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                    )
                    if text:
                        pieces.append(str(text))
        if pieces:
            return "\n".join(pieces)

    if not isinstance(response, (bytes, bytearray, dict)) and hasattr(response, "__iter__"):
        streamed = _collect_stream_text(response, stream_callback=stream_callback)
        if streamed:
            return streamed

    return str(response)


def _get_field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _tool_call_function(tool_call: Any) -> Any | None:
    return _get_field(tool_call, "function")


def tool_calls_to_action_text(choice_or_message: Any) -> str:
    """Convert native Chat Completions tool_calls into MiniCodex JSON-action text."""

    message = _get_field(choice_or_message, "message", choice_or_message)
    tool_calls = _get_field(message, "tool_calls") or []
    if not tool_calls:
        return ""
    call = tool_calls[0]
    function = _tool_call_function(call)
    name = _get_field(function, "name", "") if function is not None else ""
    arguments = _get_field(function, "arguments", "{}") if function is not None else "{}"
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        args = {"_raw_arguments": arguments}
    content = _message_content(choice_or_message).strip()
    return json.dumps(
        {
            "thought": content or "Native Chat Completions tool_call returned by provider.",
            "action": str(name),
            "args": args if isinstance(args, dict) else {"value": args},
        },
        ensure_ascii=False,
    )


def _chat_tool_schema_for_action(name: str, spec: Any) -> dict[str, Any]:
    properties = {
        arg_name: spec.arg_spec(arg_name).to_json_schema() for arg_name in spec.allowed_args
    }
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": spec.description or f"Run MiniCodex action {name}.",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(spec.required),
                "additionalProperties": False,
            },
        },
    }


def build_chat_completion_tools(
    action_names: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Render MiniCodex actions as native Chat Completions tools."""

    selected = set(action_names) if action_names is not None else set(ACTION_SPECS)
    return [
        _chat_tool_schema_for_action(name, spec)
        for name, spec in sorted(ACTION_SPECS.items())
        if name in selected
    ]


def normalize_action_protocol(protocol: str | None, provider: str) -> str:
    """Normalize model action protocol selection."""

    value = (protocol or "auto").strip().lower().replace("-", "_")
    aliases = {
        "json": "json_text",
        "text": "json_text",
        "tool": "tool_calls",
        "tools": "tool_calls",
        "native": "tool_calls",
        "native_tools": "tool_calls",
    }
    value = aliases.get(value, value)
    if value not in {"auto", "json_text", "tool_calls"}:
        return "auto"
    if value == "auto":
        return "tool_calls" if provider in OPENAI_COMPATIBLE_PROVIDERS else "json_text"
    return value


def _usage_get(usage: Any, *names: str) -> int:
    for name in names:
        if usage is None:
            return 0
        if isinstance(usage, dict) and name in usage:
            try:
                return int(usage[name])
            except (TypeError, ValueError):
                return 0
        value = getattr(usage, name, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


def provider_default_base_url(provider: str) -> str | None:
    """Return default OpenAI-compatible base URL for local providers."""

    if provider == "ollama":
        return "http://localhost:11434/v1"
    if provider == "lmstudio":
        return "http://localhost:1234/v1"
    if provider == "llama_cpp":
        return "http://localhost:8000/v1"
    return None


class ModelClient:
    """Small wrapper around supported model providers.

    Provider modes:
    - ``openai`` uses the official Responses API and can request strict JSON-schema output.
    - ``openai_compatible``/``ollama``/``lmstudio``/``llama_cpp`` use Chat Completions
      against local or self-hosted OpenAI-compatible endpoints. These providers request
      JSON-object output when supported and fall back to prompt-only JSON instructions.
    - ``stub``/``echo`` never call a remote model and are safe for smoke/debug tests.
    """

    def __init__(
        self,
        model: str,
        provider: str = "openai",
        *,
        timeout_seconds: int = 60,
        max_output_tokens: int = 2048,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        structured_output: bool = True,
        call_budget: int = 60,
        cost_budget_usd: float = 0.0,
        input_price_per_million: float = 0.0,
        output_price_per_million: float = 0.0,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        reasoning_effort: str | None = None,
        stream: bool = False,
        system_prompt: str | None = None,
        action_protocol: str = "auto",
        available_actions: Iterable[str] | None = None,
        stream_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.model = model
        self.provider = provider
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_output_tokens = max(128, int(max_output_tokens))
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.structured_output = structured_output
        self.call_budget = max(1, int(call_budget))
        self.cost_budget_usd = max(0.0, float(cost_budget_usd))
        explicit_input_price = max(0.0, float(input_price_per_million))
        explicit_output_price = max(0.0, float(output_price_per_million))
        pricing = resolve_model_price(
            provider,
            model,
            explicit_input=explicit_input_price,
            explicit_output=explicit_output_price,
        )
        self.input_price_per_million = float(pricing.get("input_price_per_million", 0.0) or 0.0)
        self.output_price_per_million = float(pricing.get("output_price_per_million", 0.0) or 0.0)
        self.pricing_source = str(pricing.get("pricing_source", "unknown"))
        self.pricing_currency = str(pricing.get("currency", "USD"))
        self.pricing_notes = str(pricing.get("notes", ""))
        self.base_url = (
            base_url
            or os.getenv("MINICODEX_MODEL_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or provider_default_base_url(provider)
        )
        self.api_key_env = api_key_env or "OPENAI_API_KEY"
        self.api_key = api_key
        self.reasoning_effort = (reasoning_effort or "").strip() or None
        self.stream = bool(stream)
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.action_protocol = normalize_action_protocol(action_protocol, provider)
        self.available_actions = (
            tuple(sorted(set(available_actions))) if available_actions is not None else None
        )
        self.stream_callback = stream_callback
        self.usage = ModelUsage()
        self.client = None
        get_provider_info(provider)
        if provider == "openai" or provider in OPENAI_COMPATIBLE_PROVIDERS:
            try:
                from openai import OpenAI
            except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
                raise RuntimeError(
                    "openai paketi kurulu değil. `pip install openai` veya `pip install -e .` çalıştırın."
                ) from exc
            resolved_api_key = self._resolved_api_key()
            kwargs: dict[str, Any] = {"api_key": resolved_api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self.client = OpenAI(**kwargs)

    def _resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        value = os.getenv(self.api_key_env)
        if value:
            return value
        if self.provider in OPENAI_COMPATIBLE_PROVIDERS:
            # Local OpenAI-compatible servers usually ignore the key, but the SDK requires one.
            return "minicodex-local"
        return os.getenv("OPENAI_API_KEY", "")

    def _structured_output_format(self) -> dict[str, Any]:
        return {
            "format": {
                "type": "json_schema",
                "name": "minicodex_model_action",
                "schema": MODEL_ACTION_JSON_SCHEMA,
                "strict": True,
            }
        }

    def _repair_prompt(
        self, prompt: str, repair_error: str | None, invalid_output: str | None
    ) -> str:
        if not repair_error:
            return prompt
        repair_payload = {
            "repair_instruction": (
                "Your previous response did not satisfy the MiniCodex JSON action schema. "
                "Return exactly one corrected JSON object with only thought, action, and args. "
                "Do not use unsupported args and do not include markdown."
            ),
            "validation_error": repair_error,
            "invalid_output_preview": truncate(invalid_output or "", 4000),
            "original_prompt": json.loads(prompt) if prompt.strip().startswith("{") else prompt,
        }
        return json.dumps(repair_payload, ensure_ascii=False, indent=2)

    def _ensure_budget_before_call(self) -> None:
        if self.usage.calls >= self.call_budget:
            raise ModelBudgetExceeded(
                f"Model call budget exceeded: {self.usage.calls}/{self.call_budget} calls used."
            )
        if self.cost_budget_usd > 0 and self.usage.estimated_cost_usd >= self.cost_budget_usd:
            raise ModelBudgetExceeded(
                "Estimated model cost budget exceeded: "
                f"${self.usage.estimated_cost_usd:.6f}/${self.cost_budget_usd:.6f}."
            )

    def _reserve_call_attempt(self) -> None:
        """Reserve budget for one provider attempt, successful or failed."""

        self._ensure_budget_before_call()
        self.usage.calls += 1

    def _record_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        input_tokens = _usage_get(usage, "input_tokens", "prompt_tokens")
        output_tokens = _usage_get(usage, "output_tokens", "completion_tokens")
        self.usage.input_tokens += input_tokens
        self.usage.output_tokens += output_tokens
        self.usage.estimated_cost_usd = (
            self.usage.input_tokens * self.input_price_per_million / 1_000_000
            + self.usage.output_tokens * self.output_price_per_million / 1_000_000
        )
        if self.cost_budget_usd > 0 and self.usage.estimated_cost_usd > self.cost_budget_usd:
            raise ModelBudgetExceeded(
                "Estimated model cost budget exceeded after response: "
                f"${self.usage.estimated_cost_usd:.6f}/${self.cost_budget_usd:.6f}."
            )

    def _create_responses(self, request_prompt: str) -> Any:
        assert self.client is not None
        call_args: dict[str, Any] = {
            "model": self.model,
            "instructions": self.system_prompt,
            "input": request_prompt,
            "max_output_tokens": self.max_output_tokens,
            "timeout": self.timeout_seconds,
        }
        if self.structured_output:
            call_args["text"] = self._structured_output_format()
        if self.reasoning_effort and self.reasoning_effort not in {"none", "off"}:
            call_args["reasoning"] = {"effort": self.reasoning_effort}
        if self.stream:
            call_args["stream"] = True
        try:
            return self.client.responses.create(**call_args)
        except TypeError as first_error:
            response = None
            last_type_error: TypeError = first_error
            # Older SDKs or non-Codex models may reject newer knobs. Remove the smallest
            # incompatible subset first so timeout/token limits are preserved whenever possible.
            for keys_to_remove in (
                ("text",),
                ("reasoning",),
                ("stream",),
                ("text", "reasoning"),
                ("text", "stream"),
                ("reasoning", "stream"),
                ("text", "timeout"),
                ("text", "max_output_tokens"),
                ("text", "reasoning", "stream"),
                ("text", "timeout", "max_output_tokens"),
            ):
                fallback_args = {
                    key: value for key, value in call_args.items() if key not in keys_to_remove
                }
                try:
                    response = self.client.responses.create(**fallback_args)
                    break
                except TypeError as exc:
                    last_type_error = exc
            if response is None:
                raise last_type_error from first_error
            return response

    def _create_chat_completion(self, request_prompt: str, *, protocol: str | None = None) -> Any:
        assert self.client is not None
        selected_protocol = normalize_action_protocol(
            protocol or self.action_protocol, self.provider
        )
        use_tool_calls = selected_protocol == "tool_calls"
        if use_tool_calls:
            system = (
                self.system_prompt
                + "\n\nUse exactly one native Chat Completions tool call for the next MiniCodex action. "
                "Do not return JSON text when tools are available. The tool name is the MiniCodex action; "
                "the tool arguments are exactly that action's args object. Keep any visible message content brief."
            )
        else:
            system = (
                self.system_prompt
                + "\n\nReturn exactly one JSON object with top-level keys thought, action, and args. "
                "Do not include markdown fences or explanatory text outside JSON."
            )
        call_args: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": request_prompt},
            ],
            "max_tokens": self.max_output_tokens,
            "timeout": self.timeout_seconds,
        }
        if use_tool_calls:
            call_args["tools"] = build_chat_completion_tools(self.available_actions)
            call_args["tool_choice"] = "auto"
        elif self.structured_output:
            call_args["response_format"] = {"type": "json_object"}
        if self.reasoning_effort and self.reasoning_effort not in {"none", "off"}:
            call_args["reasoning_effort"] = self.reasoning_effort
        if self.stream:
            call_args["stream"] = True
        try:
            return self.client.chat.completions.create(**call_args)
        except TypeError as first_error:
            response = None
            last_type_error: TypeError = first_error
            # Fallback intentionally moves from native tools -> JSON text when a local
            # OpenAI-compatible server does not implement Chat Completions tools.
            if use_tool_calls:
                fallback_args = {
                    key: value
                    for key, value in call_args.items()
                    if key not in {"tools", "tool_choice"}
                }
                if self.structured_output:
                    fallback_args["response_format"] = {"type": "json_object"}
                try:
                    response = self.client.chat.completions.create(**fallback_args)
                    return response
                except TypeError as exc:
                    last_type_error = exc
                    call_args = fallback_args
            for keys_to_remove in (
                ("response_format",),
                ("reasoning_effort",),
                ("stream",),
                ("response_format", "reasoning_effort"),
                ("response_format", "stream"),
                ("response_format", "timeout"),
                ("response_format", "max_tokens"),
                ("response_format", "reasoning_effort", "stream"),
                ("response_format", "timeout", "max_tokens"),
            ):
                fallback_args = {
                    key: value for key, value in call_args.items() if key not in keys_to_remove
                }
                try:
                    response = self.client.chat.completions.create(**fallback_args)
                    break
                except TypeError as exc:
                    last_type_error = exc
            if response is None:
                raise last_type_error from first_error
            return response

    def next_action_text(
        self,
        prompt: str,
        *,
        repair_error: str | None = None,
        invalid_output: str | None = None,
    ) -> str:
        """Return raw provider text for the next action.

        The agent validates the returned object against action_schema. Keeping
        raw text available lets the repair loop include the invalid output.
        """

        if self.provider == "stub":
            return json.dumps(
                {
                    "thought": "Stub provider is active; no real model call was made.",
                    "action": "finish",
                    "args": {
                        "summary": "Stub provider smoke test completed.",
                        "changed_files": [],
                        "checks_run": [],
                        "next_steps": ["Run a real task with the OpenAI provider."],
                    },
                },
                ensure_ascii=False,
            )

        if self.provider == "echo":
            return json.dumps(
                {
                    "thought": "Echo provider is active; prompt preview was returned in the finish output.",
                    "action": "finish",
                    "args": {
                        "summary": "Echo provider completed. Prompt preview: "
                        + truncate(prompt, 800),
                        "changed_files": [],
                        "checks_run": [],
                        "next_steps": ["Run a real task with the OpenAI provider."],
                    },
                },
                ensure_ascii=False,
            )

        if self.provider != "openai" and self.provider not in OPENAI_COMPATIBLE_PROVIDERS:
            raise ValueError(f"Unsupported provider: {self.provider}")

        request_prompt = self._repair_prompt(prompt, repair_error, invalid_output)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._reserve_call_attempt()
            try:
                if self.provider == "openai":
                    response = self._create_responses(request_prompt)
                else:
                    response = self._create_chat_completion(request_prompt)
                self._record_usage(response)
                text = response_to_text(response, stream_callback=self.stream_callback)
                choice = _first_choice(response)
                if choice is not None and tool_calls_to_action_text(choice):
                    self.usage.native_tool_calls += 1
                else:
                    self.usage.json_text_actions += 1
                if repair_error:
                    self.usage.repair_prompts += 1
                return text
            except ModelBudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - provider exceptions differ by SDK/version
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.retry_backoff_seconds * (2**attempt))
        raise ModelCallError(
            f"Model provider call failed after {self.max_retries + 1} attempt(s): {last_error}"
        )

    def record_action_validation(self, ok: bool) -> None:
        """Record whether the parsed provider action satisfied the MiniCodex schema."""

        if ok:
            self.usage.action_validation_successes += 1
        else:
            self.usage.action_validation_failures += 1

    def to_usage_dict(self) -> dict[str, Any]:
        """Return usage plus provider/model pricing metadata for telemetry/evals."""

        data = self.usage.to_dict()
        data.update(
            {
                "provider": self.provider,
                "model": self.model,
                "input_price_per_million": self.input_price_per_million,
                "output_price_per_million": self.output_price_per_million,
                "pricing_source": self.pricing_source,
                "pricing_currency": self.pricing_currency,
                "pricing_notes": self.pricing_notes,
            }
        )
        return data

    def schema_reliability_report(self) -> dict[str, Any]:
        """Return provider action-protocol and schema reliability metrics."""

        total = self.usage.action_validation_successes + self.usage.action_validation_failures
        return {
            "provider": self.provider,
            "model": self.model,
            "action_protocol": self.action_protocol,
            "native_tool_calls": self.usage.native_tool_calls,
            "json_text_actions": self.usage.json_text_actions,
            "validation_successes": self.usage.action_validation_successes,
            "validation_failures": self.usage.action_validation_failures,
            "repair_prompts": self.usage.repair_prompts,
            "schema_reliability": self.usage.schema_reliability,
            "observations": total,
            "input_price_per_million": self.input_price_per_million,
            "output_price_per_million": self.output_price_per_million,
            "pricing_source": self.pricing_source,
            "pricing_currency": self.pricing_currency,
            "pricing_notes": self.pricing_notes,
        }

    def next_action(
        self,
        prompt: str,
        *,
        repair_error: str | None = None,
        invalid_output: str | None = None,
    ) -> dict[str, Any]:
        """Ask the model for the next JSON action and parse it."""

        raw = self.next_action_text(
            prompt,
            repair_error=repair_error,
            invalid_output=invalid_output,
        )
        try:
            parsed = extract_json(raw)
        except Exception as exc:  # noqa: BLE001 - normalize parser failures
            raise ModelOutputParseError(
                f"Could not parse model output as JSON: {exc}", raw
            ) from exc
        return parsed
