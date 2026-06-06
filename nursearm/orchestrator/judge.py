"""Compatibility entry point for the active local NurseArm orchestrator."""

from nursearm.orchestrator.ollama_agent import OllamaMCPAgent, OllamaUnavailableError

Judge = OllamaMCPAgent

__all__ = ["Judge", "OllamaMCPAgent", "OllamaUnavailableError"]
