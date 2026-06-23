"""Ollama local LLM — official ollama Python client (Gemma 4, etc.)."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

from collections.abc import Callable, Iterator

from ollama import Client

from agent.runtime.llm_types import ModelResponse, make_function_call, make_message, new_call_id
from agent.runtime.tools import normalize_tool_name

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:e4b")
OLLAMA_ORCHESTRATOR_MODEL = os.environ.get("OLLAMA_ORCHESTRATOR_MODEL", "gemma4:e4b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_THINK = os.environ.get("OLLAMA_THINK", "true").lower() in ("1", "true", "yes")

# Gemma 4 (Ollama docs): <|think|> enables reasoning; content uses channel tokens.
GEMMA4_THINK_TRIGGER = "<|think|>"
GEMMA4_THOUGHT_OPEN = "<|channel>thought"
GEMMA4_CHANNEL_CLOSE = "<channel|>"

ChunkCallback = Callable[[str, str], None]

_ollama_client: Client | None = None
_cached_tags: list[str] | None = None


def _tags_url() -> str:
    base = OLLAMA_HOST.rstrip("/")
    return f"{base}/api/tags"


def ollama_server_up() -> bool:
    try:
        req = urllib.request.Request(_tags_url(), method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def list_ollama_models() -> list[str]:
    global _cached_tags
    if _cached_tags is not None:
        return _cached_tags
    try:
        req = urllib.request.Request(_tags_url(), method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        _cached_tags = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        return _cached_tags
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.debug("Ollama tags failed: %s", exc)
        return []


def resolve_ollama_model() -> str:
    """Pick configured model or first sensible fallback on disk."""
    models = list_ollama_models()
    if not models:
        return OLLAMA_MODEL

    wanted = OLLAMA_MODEL
    if wanted in models:
        return wanted
    base = wanted.split(":")[0]
    for name in models:
        if name == base or name.startswith(f"{base}:"):
            return name
    for pref in ("gemma4", "gemma3", "llama3.2", "llama3.1", "qwen3"):
        for name in models:
            if name.startswith(pref):
                return name
    return models[0]


def resolve_ollama_orchestrator_model() -> str:
    """Faster/smaller model for routing — falls back to main model."""
    models = list_ollama_models()
    wanted = OLLAMA_ORCHESTRATOR_MODEL
    if not models:
        return wanted or OLLAMA_MODEL
    if wanted in models:
        return wanted
    base = wanted.split(":")[0]
    for name in models:
        if name == base or name.startswith(f"{base}:"):
            return name
    return resolve_ollama_model()


def ollama_available() -> bool:
    if os.environ.get("OLLAMA_ENABLED", "true").lower() in ("0", "false", "no"):
        return False
    return ollama_server_up()


def _get_ollama_client() -> Client:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = Client(host=OLLAMA_HOST.rstrip("/"))
    return _ollama_client


def _responses_tools_to_openai(tools: list | None) -> list[dict] | None:
    if not tools:
        return None
    out: list[dict] = []
    for tool in tools:
        name = tool.get("name") or tool.get("function", {}).get("name")
        if not name:
            continue
        desc = tool.get("description") or tool.get("function", {}).get("description") or ""
        params = tool.get("parameters") or tool.get("function", {}).get("parameters") or {
            "type": "object",
            "properties": {},
        }
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": params,
            },
        })
    return out or None


def _parse_tool_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _messages_for_ollama_client(messages: list[dict]) -> list[dict]:
    """Normalize internal chat messages for the official ollama Python client."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            tool_calls: list[dict] = []
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                tool_calls.append({
                    "id": tc.get("id") or new_call_id(),
                    "type": "function",
                    "function": {
                        "name": fn.get("name") or "",
                        "arguments": _parse_tool_arguments(fn.get("arguments")),
                    },
                })
            entry: dict = {"role": "assistant", "content": m.get("content") or ""}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
            continue
        if role == "tool":
            entry = {
                "role": "tool",
                "content": m.get("content") or "",
            }
            if m.get("tool_call_id"):
                entry["tool_call_id"] = m["tool_call_id"]
            out.append(entry)
            continue
        if role in ("system", "user", "assistant"):
            content = m.get("content")
            images = m.get("images")
            if role == "user" and images:
                entry: dict = {"role": "user", "images": images}
                if content is not None:
                    entry["content"] = content
                else:
                    entry["content"] = " "
                out.append(entry)
                continue
            if content is not None:
                out.append({"role": role, "content": content})
    return out


def _parse_ollama_tool_calls(tool_calls: list | None) -> list:
    output = []
    for tc in tool_calls or []:
        if hasattr(tc, "model_dump"):
            tc = tc.model_dump()
        fn = tc.get("function") or {}
        if hasattr(fn, "model_dump"):
            fn = fn.model_dump()
        name = normalize_tool_name(fn.get("name") or "")
        args = fn.get("arguments") or {}
        if isinstance(args, dict):
            args = json.dumps(args)
        if name:
            output.append(make_function_call(
                name,
                args,
                call_id=tc.get("id") or new_call_id(),
            ))
    return output


def _ollama_message_dict(msg) -> dict:
    if hasattr(msg, "model_dump"):
        return msg.model_dump()
    if isinstance(msg, dict):
        return msg
    return {}


def _ollama_chat_options(model: str, temperature: float, max_output_tokens: int) -> dict:
    return _gemma4_sampling_options(model, temperature, max_output_tokens)


def _use_ollama_think(model: str, think: bool | None = None) -> bool:
    use_think = OLLAMA_THINK if think is None else think
    return bool(use_think and _model_supports_thinking(model))


def _response_from_ollama_message(msg, *, thinking_parts: list[str], text_parts: list[str]) -> ModelResponse:
    data = _ollama_message_dict(msg)
    thinking = (data.get("thinking") or "").strip()
    if thinking:
        thinking_parts.append(thinking)
    content = (data.get("content") or "").strip()
    if content:
        text_parts.append(content)

    output = _parse_ollama_tool_calls(data.get("tool_calls"))
    text = "\n".join(text_parts).strip()
    thinking_text = "\n".join(thinking_parts).strip()
    if not text and thinking_text:
        text = extract_visible_reply_from_thinking(thinking_text)
    if text and not output:
        output.append(make_message(text))
    return ModelResponse(output=output, output_text=text, thinking_text=thinking_text)


def _is_gemma4(model: str) -> bool:
    name = model.lower()
    return name.startswith("gemma4") or name.startswith("gemma-4")


def _model_supports_thinking(model: str) -> bool:
    """Only models with Ollama native thinking (e.g. Gemma 4) accept think=true."""
    return _is_gemma4(model)


def _prepare_system_prompt(instructions: str, model: str, *, think: bool | None = None) -> str:
    """Gemma 4: prepend <|think|> to enable reasoning mode (Ollama chat template)."""
    use_think = OLLAMA_THINK if think is None else think
    if not use_think or not _is_gemma4(model):
        return instructions
    if GEMMA4_THINK_TRIGGER in instructions:
        return instructions
    return f"{GEMMA4_THINK_TRIGGER}\n{instructions}"


def _gemma4_sampling_options(model: str, temperature: float, max_output_tokens: int) -> dict:
    """Gemma 4 best-practice sampling (temp=1, top_p=0.95, top_k=64)."""
    opts: dict = {"num_predict": max_output_tokens}
    if not _is_gemma4(model):
        opts["temperature"] = temperature
        return opts
    override = os.environ.get("OLLAMA_GEMMA4_TEMP", "").strip()
    opts["temperature"] = float(override) if override else 1.0
    opts["top_p"] = float(os.environ.get("OLLAMA_GEMMA4_TOP_P", "0.95"))
    opts["top_k"] = int(os.environ.get("OLLAMA_GEMMA4_TOP_K", "64"))
    return opts


def _strip_gemma4_channels(text: str) -> tuple[str, str]:
    """Split Gemma 4 <|channel>thought … <channel|> answer format."""
    thinking_parts: list[str] = []
    answer = text
    pattern = (
        re.escape(GEMMA4_THOUGHT_OPEN)
        + r"\n?(.*?)"
        + re.escape(GEMMA4_CHANNEL_CLOSE)
    )
    for match in re.finditer(pattern, answer, flags=re.DOTALL):
        body = match.group(1).strip()
        if body:
            thinking_parts.append(body)
    answer = re.sub(pattern, "", answer, flags=re.DOTALL)
    return "\n\n".join(thinking_parts).strip(), answer.strip()


def _visible_answer_text(text: str) -> str:
    """User-facing answer only — strip all thinking blocks (for history)."""
    _, from_channels = _strip_gemma4_channels(text)
    _, from_tags = _split_thinking_and_answer(from_channels)
    return from_tags


def _input_items_to_messages(
    instructions: str,
    input_items: list,
    *,
    model: str = "",
    think: bool | None = None,
) -> list[dict]:
    system = (
        _prepare_system_prompt(instructions, model, think=think)
        if model
        else instructions
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    pending_calls: list[dict] = []

    def flush_calls() -> None:
        nonlocal pending_calls
        if not pending_calls:
            return
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": pending_calls,
        })
        pending_calls = []

    for item in input_items:
        role = item.get("role")
        if role in ("user", "assistant"):
            flush_calls()
            content = item.get("content") or ""
            images = item.get("images")
            if role == "user" and images:
                entry: dict = {"role": "user", "images": images, "content": content or " "}
                messages.append(entry)
                continue
            if content:
                if role == "assistant":
                    content = _visible_answer_text(content)
                if content:
                    messages.append({"role": role, "content": content})
            continue

        if item.get("type") == "function_call":
            cid = item.get("call_id") or item.get("id") or new_call_id()
            pending_calls.append({
                "id": cid,
                "type": "function",
                "function": {
                    "name": item.get("name", ""),
                    "arguments": item.get("arguments") or "{}",
                },
            })
            continue

        if item.get("type") == "function_call_output":
            flush_calls()
            cid = item.get("call_id") or item.get("id") or new_call_id()
            raw = item.get("output", "")
            messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "content": raw if isinstance(raw, str) else json.dumps(raw),
            })

    flush_calls()
    return messages


def _thinking_tag(name: str, *, close: bool = False) -> str:
    return f"</{name}>" if close else f"<{name}>"


_THINKING_NAMES = ("redacted_thinking", "think", "thinking")


def _split_thinking_and_answer(text: str) -> tuple[str, str]:
    """Split thinking blocks from user-facing answer (Gemma 4 channels + legacy tags)."""
    thinking_parts: list[str] = []
    answer = text

    channel_thinking, answer = _strip_gemma4_channels(answer)
    if channel_thinking:
        thinking_parts.append(channel_thinking)

    for name in _THINKING_NAMES:
        open_tag = _thinking_tag(name)
        close_tag = _thinking_tag(name, close=True)
        pattern = re.escape(open_tag) + r"(.*?)" + re.escape(close_tag)
        for match in re.finditer(pattern, answer, flags=re.DOTALL | re.IGNORECASE):
            body = match.group(1).strip()
            if body:
                thinking_parts.append(body)
        answer = re.sub(pattern, "", answer, flags=re.DOTALL | re.IGNORECASE)
    return "\n\n".join(thinking_parts).strip(), answer.strip()


def extract_visible_reply_from_thinking(thinking: str) -> str:
    """When Ollama streams only `message.thinking`, pull the user-facing reply."""
    text = thinking.strip()
    if not text:
        return ""

    def _looks_like_meta(line: str) -> bool:
        if "**" in line or line.startswith(("*", "-", "#", "•")):
            return True
        if re.search(
            r"\b(step|structure|consider|analyze|acknowledge|greeting/|thinking process)\b",
            line,
            re.I,
        ):
            return True
        return False

    patterns = (
        r'final\s+response\s*(?:\*\*)?\s*:\s*["\'](.+?)["\']',
        r'(?:\*\*)?(?:final\s+response|assistant\s+response|user[- ]facing\s+response|reply)\s*(?:\*\*)?\s*:\s*["\']?(.+?)["\']?\s*$',
    )
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if match:
            candidate = match.group(1).strip().strip('"\'').strip()
            if 2 < len(candidate) < 2000 and not _looks_like_meta(candidate):
                return candidate

    for match in re.finditer(
        r'["\']?((?:Hi|Hello|Hey)[!,.]?\s[^"\n]{4,200})["\']?',
        text,
        re.IGNORECASE,
    ):
        candidate = match.group(1).strip().strip('"\'').strip()
        if 8 < len(candidate) < 400 and not _looks_like_meta(candidate):
            return candidate

    for match in re.finditer(r'"([^"]{8,200})"', text):
        candidate = match.group(1).strip()
        if not _looks_like_meta(candidate) and re.match(r"^(Hi|Hello|Hey)", candidate, re.I):
            return candidate

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if _looks_like_meta(line):
            continue
        if line.endswith(":"):
            continue
        cleaned = line.strip('"\'').strip()
        if 8 < len(cleaned) < 300:
            return cleaned

    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in reversed(sentences):
        cleaned = sentence.strip().strip('"\'').strip()
        if _looks_like_meta(cleaned):
            continue
        if 12 < len(cleaned) < 300 and not re.match(r"^\d+\.", cleaned):
            return cleaned

    return ""


def _partial_control_token_hold(buf: str) -> int:
    """Hold suffix bytes that may be the start of a Gemma control token."""
    markers = [GEMMA4_THOUGHT_OPEN, GEMMA4_CHANNEL_CLOSE]
    markers += [_thinking_tag(n) for n in _THINKING_NAMES]
    markers += [_thinking_tag(n, close=True) for n in _THINKING_NAMES]
    hold = 0
    for marker in markers:
        for i in range(1, len(marker)):
            if buf.endswith(marker[:i]):
                hold = max(hold, i)
    return hold


class _ThinkingStreamParser:
    """Incremental splitter — Gemma 4 <|channel>thought … <channel|> plus legacy tags."""

    def __init__(self) -> None:
        self._buf = ""
        self._in_gemma4_thought = False
        self._in_thinking = False
        self._active_tag: str | None = None

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self._buf += chunk
        out: list[tuple[str, str]] = []

        while self._buf:
            if self._in_gemma4_thought:
                idx = self._buf.find(GEMMA4_CHANNEL_CLOSE)
                if idx < 0:
                    hold = len(GEMMA4_CHANNEL_CLOSE) - 1
                    emit_len = max(0, len(self._buf) - hold)
                    if emit_len > 0:
                        out.append(("thinking", self._buf[:emit_len]))
                        self._buf = self._buf[emit_len:]
                    break
                if idx > 0:
                    out.append(("thinking", self._buf[:idx]))
                self._buf = self._buf[idx + len(GEMMA4_CHANNEL_CLOSE):]
                if self._buf.startswith("\n"):
                    self._buf = self._buf[1:]
                self._in_gemma4_thought = False
                continue

            open_idx = self._buf.find(GEMMA4_THOUGHT_OPEN)
            if open_idx >= 0:
                if open_idx > 0:
                    out.append(("text", self._buf[:open_idx]))
                rest = self._buf[open_idx + len(GEMMA4_THOUGHT_OPEN):]
                if rest.startswith("\n"):
                    rest = rest[1:]
                self._buf = rest
                self._in_gemma4_thought = True
                continue

            if self._in_thinking and self._active_tag:
                close_tag = _thinking_tag(self._active_tag, close=True)
                idx = self._buf.lower().find(close_tag.lower())
                if idx < 0:
                    emit_len = max(0, len(self._buf) - len(close_tag) + 1)
                    if emit_len > 0:
                        out.append(("thinking", self._buf[:emit_len]))
                        self._buf = self._buf[emit_len:]
                    break
                if idx > 0:
                    out.append(("thinking", self._buf[:idx]))
                self._buf = self._buf[idx + len(close_tag):]
                self._in_thinking = False
                self._active_tag = None
                continue

            open_at = -1
            open_tag = ""
            open_name = ""
            lower = self._buf.lower()
            for name in _THINKING_NAMES:
                tag = _thinking_tag(name)
                idx = lower.find(tag.lower())
                if idx >= 0 and (open_at < 0 or idx < open_at):
                    open_at = idx
                    open_tag = tag
                    open_name = name

            if open_at < 0:
                hold = _partial_control_token_hold(self._buf)
                if len(self._buf) <= hold:
                    break
                emit_len = len(self._buf) - hold
                if emit_len > 0:
                    out.append(("text", self._buf[:emit_len]))
                    self._buf = self._buf[emit_len:]
                break

            if open_at > 0:
                out.append(("text", self._buf[:open_at]))
            self._buf = self._buf[open_at + len(open_tag):]
            self._in_thinking = True
            self._active_tag = open_name

        return out

    def flush(self) -> list[tuple[str, str]]:
        """Emit any trailing buffer at end of stream."""
        if not self._buf:
            return []
        if self._in_gemma4_thought:
            out = [("thinking", self._buf)]
        elif self._in_thinking:
            out = [("thinking", self._buf)]
        else:
            out = [("text", self._buf)]
        self._buf = ""
        self._in_gemma4_thought = False
        self._in_thinking = False
        self._active_tag = None
        return out


def call_ollama(
    *,
    instructions: str,
    input_items: list,
    tools: list | None,
    temperature: float,
    max_output_tokens: int,
    agent: str = "",
    on_chunk: ChunkCallback | None = None,
    think: bool | None = None,
) -> ModelResponse | None:
    from agent.runtime.agent_log import llm_timer

    if not ollama_available():
        return None

    client = _get_ollama_client()
    model = (
        resolve_ollama_orchestrator_model()
        if agent == "orchestrator"
        else resolve_ollama_model()
    )
    messages = _messages_for_ollama_client(
        _input_items_to_messages(instructions, input_items, model=model, think=think),
    )
    ollama_tools = _responses_tools_to_openai(tools)
    options = _ollama_chat_options(model, temperature, max_output_tokens)
    use_think = _use_ollama_think(model, think=think)

    try:
        with llm_timer("ollama", model, agent=agent, tools=len(tools or [])):
            if on_chunk is not None:
                result = _call_ollama_live(
                    client=client,
                    model=model,
                    messages=messages,
                    ollama_tools=ollama_tools,
                    options=options,
                    on_chunk=on_chunk,
                    use_think=use_think,
                )
            else:
                response = client.chat(
                    model=model,
                    messages=messages,
                    tools=ollama_tools,
                    think=use_think or None,
                    options=options,
                )
                result = _response_from_ollama_message(
                    response.message,
                    thinking_parts=[],
                    text_parts=[],
                )
        result.provider = "ollama"
        if result.thinking_text:
            from agent.runtime.agent_log import llm as log_llm
            log_llm(
                "think",
                provider="ollama",
                model=model,
                agent=agent or None,
                chars=len(result.thinking_text),
            )
        return result
    except Exception as exc:
        logger.warning("Ollama chat failed: %s", exc)
        return None


def _call_ollama_live(
    *,
    client: Client,
    model: str,
    messages: list[dict],
    ollama_tools: list[dict] | None,
    options: dict,
    on_chunk: ChunkCallback,
    use_think: bool,
) -> ModelResponse:
    """Stream thinking + text via official ollama.chat(stream=True)."""
    parser = _ThinkingStreamParser()
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    last_tool_calls: list | None = None

    for chunk in client.chat(
        model=model,
        messages=messages,
        tools=ollama_tools,
        stream=True,
        think=use_think or None,
        options=options,
    ):
        data = _ollama_message_dict(chunk.message)
        thinking = data.get("thinking") or ""
        content = data.get("content") or ""
        if data.get("tool_calls"):
            last_tool_calls = data["tool_calls"]

        if thinking:
            on_chunk("thinking", thinking)
            thinking_parts.append(thinking)
        if content:
            for channel, piece in parser.feed(content):
                if not piece:
                    continue
                on_chunk(channel, piece)
                if channel == "thinking":
                    thinking_parts.append(piece)
                else:
                    text_parts.append(piece)

    for channel, piece in parser.flush():
        if not piece:
            continue
        on_chunk(channel, piece)
        if channel == "thinking":
            thinking_parts.append(piece)
        else:
            text_parts.append(piece)

    text = "".join(text_parts).strip()
    thinking_text = "".join(thinking_parts).strip()
    if not text and thinking_text:
        text = extract_visible_reply_from_thinking(thinking_text)

    output = _parse_ollama_tool_calls(last_tool_calls)
    if text and not output:
        output.append(make_message(text))
    return ModelResponse(output=output, output_text=text, thinking_text=thinking_text)


def stream_ollama_text(
    *,
    instructions: str,
    input_items: list,
    temperature: float,
    max_output_tokens: int,
    think: bool | None = None,
) -> Iterator[tuple[str, str]]:
    """Yield (channel, text) tuples — channel is 'thinking' or 'text'."""
    if not ollama_available():
        return

    client = _get_ollama_client()
    model = resolve_ollama_model()
    messages = _messages_for_ollama_client(
        _input_items_to_messages(instructions, input_items, model=model, think=think),
    )
    parser = _ThinkingStreamParser()
    options = _ollama_chat_options(model, temperature, max_output_tokens)
    use_think = _use_ollama_think(model, think)

    for chunk in client.chat(
        model=model,
        messages=messages,
        stream=True,
        think=use_think or None,
        options=options,
    ):
        data = _ollama_message_dict(chunk.message)
        thinking = data.get("thinking") or ""
        content = data.get("content") or ""
        if thinking:
            yield ("thinking", thinking)
        if content:
            for channel, piece in parser.feed(content):
                if piece:
                    yield (channel, piece)

    for channel, piece in parser.flush():
        if piece:
            yield (channel, piece)
