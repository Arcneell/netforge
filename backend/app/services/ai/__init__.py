"""AI integration package — provider-agnostic clients and feature services.

Public surface:
- `get_provider()` returns a configured `AIProvider` based on env settings.
- `suggest_links` (and future `advisor`, `nl_query`) wraps a feature call,
  records the run in `ai_run_logs`, and persists structured outputs.

Designed so the rest of the app never imports a specific SDK — provider
swap is a config change, not a code change.
"""

from app.services.ai.providers import get_provider
from app.services.ai.types import (
    AICompletion,
    AIProviderError,
    AIProviderRateLimitError,
    AIUnsupportedFeatureError,
    TokenUsage,
    ToolCall,
    ToolDef,
)

__all__ = [
    "AICompletion",
    "AIProviderError",
    "AIProviderRateLimitError",
    "AIUnsupportedFeatureError",
    "TokenUsage",
    "ToolCall",
    "ToolDef",
    "get_provider",
]
