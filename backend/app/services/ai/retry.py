"""Small app-level retry helper for the non-streaming provider call path.

The retry wraps ONLY the "the provider told us to slow down" case — a
single extra attempt after a short backoff. This lives at the service
layer (not inside `AIProvider.call()` itself) because giving up after ONE
retry with a fixed short delay is a product choice for an interactive admin
UI: an operator staring at a spinner should get an answer or a clear error
within a few seconds, not be silently retried forever.

Streaming calls are intentionally NOT wrapped here — by the time a rate
limit surfaces mid-stream, partial text may already be on the wire to the
client, and re-issuing the whole call would duplicate/garble the output.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.services.ai.types import AIProviderRateLimitError

logger = logging.getLogger("netforge.ai")

# Short and fixed on purpose — see module docstring. Long enough to clear a
# brief burst limit, short enough that the operator isn't left waiting on a
# retry that has a good chance of hitting the same 429/529.
_RETRY_BACKOFF_SECONDS = 1.5


async def call_with_retry[T](call: Callable[[], Awaitable[T]]) -> T:
    """Run `call()`, retrying exactly once if it raises
    `AIProviderRateLimitError`. Any other exception — including a second
    rate-limit hit on the retry — propagates unchanged to the caller, which
    already handles `AIProviderError` (the retry's base class)."""
    try:
        return await call()
    except AIProviderRateLimitError:
        logger.warning(
            "ai.provider_call: rate limited by provider, retrying once after %.1fs",
            _RETRY_BACKOFF_SECONDS,
        )
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
        return await call()
