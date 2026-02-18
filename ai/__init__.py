import os

_provider = None


def get_provider():
    """Return the configured AI provider, or None if AI is not configured."""
    global _provider
    if _provider is not None:
        return _provider

    ai_type = os.environ.get("AI_PROVIDER", "").lower()
    if ai_type == "anthropic":
        from .anthropic import AnthropicProvider
        _provider = AnthropicProvider()
    elif ai_type == "ollama":
        from .ollama import OllamaProvider
        _provider = OllamaProvider()

    return _provider


def is_available() -> bool:
    try:
        return get_provider() is not None
    except Exception:
        return False
