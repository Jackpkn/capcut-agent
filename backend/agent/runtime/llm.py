"""Multi-provider LLM: Groq + Gemini with auto-fallback on rate/token limits."""

from __future__ import annotations

import json
import logging
import os
from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from agent.runtime.llm_types import ModelResponse, make_function_call, make_message, new_call_id

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
    return groq_available() or gemini_available()


def provider_order(explicit: str | None = None) -> list[str]:
    """Resolve provider try-order: auto (primary + fallback), groq-only, or gemini-only."""
    mode = (explicit or os.environ.get("LLM_PROVIDER", "auto")).lower()
    has_groq = groq_available()
    has_gemini = gemini_available()

    if mode == "groq":
        return ["groq"] if has_groq else []
    if mode == "gemini":
        return ["gemini"] if has_gemini else []

    primary = os.environ.get("LLM_PRIMARY", "groq").lower()
    secondary = "gemini" if primary == "groq" else "groq"
    order: list[str] = []
    for name in (primary, secondary):
        if name == "groq" and has_groq and "groq" not in order:
            order.append("groq")
        if name == "gemini" and has_gemini and "gemini" not in order:
            order.append("gemini")
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
) -> ModelResponse | None:
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
) -> ModelResponse | None:
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
) -> ModelResponse | None:
    """Call LLM; on rate/token limits try the next configured provider."""
    order = provider_order(provider)
    if not order:
        logger.warning("No LLM provider configured (set GROQ_API_KEY and/or GEMINI_API_KEY)")
        return None

    last_exc: BaseException | None = None
    for name in order:
        try:
            if name == "groq":
                result = _call_groq(
                    instructions=instructions,
                    input_items=input_items,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
            else:
                result = _call_gemini(
                    instructions=instructions,
                    input_items=input_items,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
            if result is not None:
                result.provider = name
                if len(order) > 1 and name != order[0]:
                    logger.info("LLM fallback: using %s (primary %s unavailable)", name, order[0])
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
):
    """Yield text deltas; falls back Groq → Gemini on stream errors."""
    order = provider_order()
    for name in order:
        try:
            if name == "groq":
                gen = _stream_groq(
                    instructions=instructions,
                    input_items=input_items,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
            else:
                gen = _stream_gemini(
                    instructions=instructions,
                    input_items=input_items,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
            yielded = False
            for delta in gen:
                yielded = True
                yield delta
            if yielded:
                return
        except Exception as exc:
            if _is_limit_error(exc):
                logger.warning("%s stream limit — trying next provider", name)
                continue
            logger.warning("%s stream failed: %s", name, exc)
            return
