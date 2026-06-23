"""Provider order for tool-calling LLM requests."""

import os

from agent.runtime.llm import provider_order, provider_order_for_tools


def test_tools_provider_prefers_ollama_by_default(monkeypatch):
    monkeypatch.delenv("LLM_TOOLS_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("LLM_PRIMARY", "ollama")
    monkeypatch.setattr("agent.runtime.llm.ollama_available", lambda: True)
    monkeypatch.setattr("agent.runtime.llm.groq_available", lambda: True)
    monkeypatch.setattr("agent.runtime.llm.gemini_available", lambda: False)

    order = provider_order_for_tools()
    assert order[0] == "ollama"
    assert "groq" in order


def test_tools_provider_prefers_groq_when_configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("LLM_PRIMARY", "ollama")
    monkeypatch.setenv("LLM_TOOLS_PROVIDER", "groq")
    monkeypatch.setattr("agent.runtime.llm.ollama_available", lambda: True)
    monkeypatch.setattr("agent.runtime.llm.groq_available", lambda: True)
    monkeypatch.setattr("agent.runtime.llm.gemini_available", lambda: False)

    order = provider_order_for_tools()
    assert order[0] == "groq"
    assert "ollama" in order
