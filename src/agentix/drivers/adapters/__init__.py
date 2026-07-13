"""Concrete driver adapters — intrinsic (open-source infra) and vendor (commercial API).

Intrinsic adapters ship with the kernel; vendor adapters require an opt-in extra:
    pip install agentix[anthropic]   # or openai, groq — see docs/vendor-licenses.md
"""

from agentix.drivers.adapters.intrinsic.huble import HubleChatDriver
from agentix.drivers.adapters.vendor.anthropic import AnthropicChatDriver
from agentix.drivers.adapters.vendor.gemini import GeminiChatDriver
from agentix.drivers.adapters.vendor.groq import GroqChatDriver
from agentix.drivers.adapters.vendor.ollama import OllamaChatDriver
from agentix.drivers.adapters.vendor.openai import OpenAIChatDriver

__all__ = [
    "AnthropicChatDriver",
    "GeminiChatDriver",
    "GroqChatDriver",
    "HubleChatDriver",
    "OllamaChatDriver",
    "OpenAIChatDriver",
]
