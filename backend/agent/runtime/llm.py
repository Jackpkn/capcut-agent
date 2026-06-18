"""Multi-provider LLM: Ollama (local) + Groq + Gemini with auto-fallback."""

from __future__ import annotations

import json
import logging
import os
from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from agent.runtime.llm_types import ModelResponse, make_function_call, make_message, new_call_id
from agent.runtime.ollama_provider import (
    call_ollama,
    list_ollama_models,
    ollama_available,
    resolve_ollama_model,
    stream_ollama_text,
)

load_dotenv()

logger = logging.getLogger(__name__)

GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_groq_client: OpenAI | None = None
_gemini_client = None


def groq_available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def gemini_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def llm_available() -> bool:
    return ollama_available() or groq_available() or gemini_available()


def _provider_ready(name: str) -> bool:
    if name == "ollama":
        return ollama_available()
    if name == "groq":
        return groq_available()
    if name == "gemini":
        return gemini_available()
    return False


def provider_order(explicit: str | None = None) -> list[str]:
    """Resolve provider try-order: ollama | groq | gemini | auto."""
    mode = (explicit or os.environ.get("LLM_PROVIDER", "auto")).lower()

    if mode == "ollama":
        return ["ollama"] if ollama_available() else []
    if mode == "groq":
        return ["groq"] if groq_available() else []
    if mode == "gemini":
        return ["gemini"] if gemini_available() else []

    primary = os.environ.get("LLM_PRIMARY", "ollama").lower()
    fallbacks = ("ollama", "groq", "gemini")
    order: list[str] = []

    if _provider_ready(primary):
        order.append(primary)

    for name in fallbacks:
        if name != primary and _provider_ready(name) and name not in order:
            order.append(name)

    return order


def provider_order_for_tools(explicit: str | None = None) -> list[str]:
    """
    Provider order when function calling matters.
    Defaults to preferring Groq over Ollama (Gemma tool-call reliability).
  """
    order = provider_order(explicit)
    if not order:
        return order
    preferred = os.environ.get("LLM_TOOLS_PROVIDER", "groq").lower()
    if preferred in order:
        return [preferred] + [n for n in order if n != preferred]
    return order


def _get_groq_client() -> OpenAI | None:
    global _groq_client
    if _groq_client is not None:
        return _groq_client
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    _groq_client = OpenAI(
        api_key=key,
        base_url="https://api.groq.com/openai/v1",
        max_retries=0,
    )
    return _groq_client


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai

        _gemini_client = genai.Client(api_key=key)
    except Exception as exc:
        logger.warning("Gemini client init failed: %s", exc)
        return None
    return _gemini_client


def _is_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if isinstance(exc, (RateLimitError, APIConnectionError)):
        return True
    if isinstance(exc, APIStatusError):
        code = getattr(exc, "status_code", None)
        if code in (429, 413, 503):
            return True
    markers = (
        "rate limit", "rate_limit", "quota", "resource_exhausted",
        "token", "tpm", "too many", "overloaded", "capacity",
    )
    return any(m in text for m in markers)


def _groq_response_to_model(response) -> ModelResponse:
    output = list(response.output)
    text = (response.output_text or "").strip()
    return ModelResponse(output=output, output_text=text)


def _call_groq(
    *,
    instructions: str,
    input_items: list,
    tools: list | None,
    temperature: float,
    max_output_tokens: int,
    agent: str = "",
) -> ModelResponse | None:
    from agent.runtime.agent_log import llm_timer
    from agent.runtime.groq_retry import call_with_groq_retry

    client = _get_groq_client()
    if client is None:
        return None

    def _create():
        return client.responses.create(
            model=GROQ_MODEL,
            instructions=instructions,
            input=input_items,
            tools=tools,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

    try:
        with llm_timer("groq", GROQ_MODEL, agent=agent, tools=len(tools or [])):
            response = call_with_groq_retry(_create, max_attempts=2, label="Groq")
    except APIConnectionError as exc:
        logger.warning("Groq connection error: %s", exc)
        return None
    if response is None:
        return None
    return _groq_response_to_model(response)


def _responses_tools_to_gemini(tools: list | None):
    if not tools:
        return None
    from google.genai import types

    decls = []
    for tool in tools:
        name = tool.get("name") or tool.get("function", {}).get("name")
        if not name:
            continue
        desc = tool.get("description") or tool.get("function", {}).get("description") or ""
        params = tool.get("parameters") or tool.get("function", {}).get("parameters") or {
            "type": "object",
            "properties": {},
        }
        decls.append(types.FunctionDeclaration(
            name=name,
            description=desc,
            parameters_json_schema=params,
        ))
    if not decls:
        return None
    return [types.Tool(function_declarations=decls)]


def _input_items_to_gemini_contents(input_items: list):
    from google.genai import types

    contents: list = []
    call_names: dict[str, str] = {}

    for item in input_items:
        role = item.get("role")
        if role in ("user", "assistant"):
            gemini_role = "user" if role == "user" else "model"
            text = item.get("content") or ""
            if text:
                contents.append(types.Content(role=gemini_role, parts=[types.Part(text=text)]))
            continue

        if item.get("type") == "function_call":
            cid = item.get("call_id") or item.get("id") or new_call_id()
            call_names[cid] = item.get("name", "")
            try:
                args = json.loads(item.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            contents.append(types.Content(
                role="model",
                parts=[types.Part(function_call=types.FunctionCall(name=item.get("name"), args=args))],
            ))
            continue

        if item.get("type") == "function_call_output":
            cid = item.get("call_id", "")
            fname = item.get("name") or call_names.get(cid, "tool")
            raw = item.get("output", "")
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                payload = {"result": raw}
            contents.append(types.Content(
                role="user",
                parts=[types.Part(function_response=types.FunctionResponse(name=fname, response=payload))],
            ))

    return contents


def _parse_gemini_response(response) -> ModelResponse:
    output: list = []
    text_parts: list[str] = []

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in content.parts or []:
            if getattr(part, "text", None):
                text_parts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                args = getattr(fc, "args", None) or {}
                if hasattr(args, "items"):
                    args_dict = dict(args)
                else:
                    args_dict = args if isinstance(args, dict) else {}
                cid = getattr(fc, "id", None) or new_call_id()
                output.append(make_function_call(fc.name, json.dumps(args_dict), call_id=cid))

    text = "\n".join(text_parts).strip()
    if text and not any(getattr(o, "type", None) == "message" for o in output):
        output.append(make_message(text))

    return ModelResponse(output=output, output_text=text)


def _call_gemini(
    *,
    instructions: str,
    input_items: list,
    tools: list | None,
    temperature: float,
    max_output_tokens: int,
    agent: str = "",
) -> ModelResponse | None:
    from agent.runtime.agent_log import llm_timer

    client = _get_gemini_client()
    if client is None:
        return None

    from google.genai import types

    contents = _input_items_to_gemini_contents(input_items)
    gemini_tools = _responses_tools_to_gemini(tools)

    config = types.GenerateContentConfig(
        system_instruction=instructions,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    if gemini_tools:
        config.tools = gemini_tools

    try:
        with llm_timer("gemini", GEMINI_MODEL, agent=agent, tools=len(tools or [])):
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=config,
            )
    except Exception as exc:
        if _is_limit_error(exc):
            from agent.runtime.groq_rate_state import mark_rate_limited

            mark_rate_limited()
        logger.warning("Gemini API error: %s", exc)
        raise

    if not response:
        return None
    return _parse_gemini_response(response)


def _stream_groq(
    *,
    instructions: str,
    input_items: list,
    tools: list | None,
    temperature: float,
    max_output_tokens: int,
):
    client = _get_groq_client()
    if client is None:
        return
    try:
        with client.responses.stream(
            model=GROQ_MODEL,
            instructions=instructions,
            input=input_items,
            tools=tools,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ) as stream:
            for event in stream:
                if event.type == "response.output_text.delta":
                    delta = getattr(event, "delta", None) or ""
                    if delta:
                        yield delta
    except (RateLimitError, APIStatusError) as exc:
        logger.warning("Groq stream error: %s", exc)


def _stream_gemini(
    *,
    instructions: str,
    input_items: list,
    temperature: float,
    max_output_tokens: int,
):
    client = _get_gemini_client()
    if client is None:
        return

    from google.genai import types

    contents = _input_items_to_gemini_contents(input_items)
    config = types.GenerateContentConfig(
        system_instruction=instructions,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    try:
        for chunk in client.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        ):
            text = getattr(chunk, "text", None) or ""
            if text:
                yield text
    except Exception as exc:
        logger.warning("Gemini stream error: %s", exc)
        raise


def call_model(
    *,
    instructions: str,
    input_items: list,
    tools: list | None,
    temperature: float = 0.4,
    max_output_tokens: int = 1536,
    provider: str | None = None,
    agent: str = "",
    emit=None,
    think: bool | None = None,
) -> ModelResponse | None:
    """Call LLM; on rate/token limits try the next configured provider."""
    from agent.runtime.agent_log import agent as log_agent, llm as log_llm
    from agent.runtime.stream_emit import make_chunk_emitter

    # Gemma 4: thinking mode fights tool calls — disable unless caller opts in.
    if think is None:
        think = not bool(tools)

    on_chunk, finalize = make_chunk_emitter(emit, agent=agent or "")

    order = provider_order_for_tools(provider) if tools else provider_order(provider)
    if not order:
        log_llm("no provider configured — start Ollama or set API keys")
        return None

    log_llm(
        "routing",
        order=",".join(order),
        agent=agent or None,
        tools=len(tools or []),
        max_tokens=max_output_tokens,
    )

    last_exc: BaseException | None = None
    for name in order:
        try:
            if name == "ollama":
                result = call_ollama(
                    instructions=instructions,
                    input_items=input_items,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    agent=agent,
                    on_chunk=on_chunk,
                    think=think,
                )
            elif name == "groq":
                result = _call_groq(
                    instructions=instructions,
                    input_items=input_items,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    agent=agent,
                )
            else:
                result = _call_gemini(
                    instructions=instructions,
                    input_items=input_items,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    agent=agent,
                )
            if result is not None:
                finalize(thinking_fallback=result.thinking_text or "")
                result.provider = name
                n_calls = sum(1 for o in result.output if getattr(o, "type", None) == "function_call")
                log_llm(
                    "response",
                    provider=name,
                    agent=agent or None,
                    tool_calls=n_calls,
                    chars=len(result.output_text or ""),
                )
                if len(order) > 1 and name != order[0]:
                    log_llm("fallback used", from_provider=order[0], to_provider=name)
                return result
        except Exception as exc:
            last_exc = exc
            if _is_limit_error(exc):
                logger.warning("%s limit error — trying next provider: %s", name, exc)
                continue
            logger.warning("%s failed (non-retryable): %s", name, exc)
            break

    if last_exc:
        logger.warning("All LLM providers failed: %s", last_exc)
    return None


def stream_model_text(
    *,
    instructions: str,
    input_items: list,
    tools: list | None = None,
    temperature: float = 0.5,
    max_output_tokens: int = 1024,
    think: bool | None = None,
):
    """Yield (channel, text) — channel is 'thinking' or 'text'."""
    order = provider_order()
    for name in order:
        try:
            if name == "ollama":
                gen = stream_ollama_text(
                    instructions=instructions,
                    input_items=input_items,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    think=think,
                )
            elif name == "groq":
                gen = (
                    ("text", delta)
                    for delta in _stream_groq(
                        instructions=instructions,
                        input_items=input_items,
                        tools=tools,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                    )
                )
            else:
                gen = (
                    ("text", delta)
                    for delta in _stream_gemini(
                        instructions=instructions,
                        input_items=input_items,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                    )
                )
            yielded = False
            for channel, delta in gen:
                if not delta:
                    continue
                yielded = True
                yield channel, delta
            if yielded:
                return
        except Exception as exc:
            if _is_limit_error(exc):
                logger.warning("%s stream limit — trying next provider", name)
                continue
            logger.warning("%s stream failed: %s", name, exc)
            continue
