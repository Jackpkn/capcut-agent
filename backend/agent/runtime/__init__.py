"""Custom multi-agent runtime — no LangGraph/CrewAI; native observe→think→tool loops."""

from agent.runtime.loop import AgentConfig, AgentRunResult, run_agent
from agent.runtime.model import groq_available, gemini_available, llm_available, ollama_available

__all__ = [
    "AgentConfig",
    "AgentRunResult",
    "run_agent",
    "groq_available",
    "gemini_available",
    "ollama_available",
    "llm_available",
]
