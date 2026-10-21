# retry.py
# Free-tier LLM APIs often answer "429 too many requests" or "503 busy".
# Failing instantly would be annoying, so we wait a little and try again
# (exponential backoff: 3s, then 6s). Every LLM client shares this helper.

import time

from backend import config
from backend.errors import LLMError

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _status_of(exc: Exception):
    # Different SDKs name the HTTP status differently.
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def friendly_error(provider: str, exc: Exception) -> LLMError:
    """Turn a raw SDK exception into a short message a beginner can act on."""
    status = _status_of(exc)
    if status == 429:
        return LLMError(f"{provider} rate limit reached. Wait a minute and try again.", 429)
    if status in (401, 403):
        return LLMError(f"{provider} rejected the API key. Check it in your .env file.", 502)
    if status == 404:
        return LLMError(
            f"{provider} could not find the model. Model names change; check the model "
            "name in .env against the provider's docs.", 502)
    return LLMError(f"{provider} request failed ({status or 'network error'}). Please try again.", 502)


def with_retry(fn, provider: str):
    """Call fn(). On a temporary failure wait and retry; otherwise raise a friendly LLMError."""
    delay = config.RETRY_BASE_DELAY_SECONDS
    for attempt in range(1, config.RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except LLMError:
            raise  # already friendly, don't wrap it again
        except Exception as exc:  # noqa: BLE001 - SDKs raise many different exception types
            retryable = (
                _status_of(exc) in RETRYABLE_STATUS
                # Groq sometimes returns a malformed tool call; a retry usually fixes it.
                or "tool_use_failed" in str(exc)
                or isinstance(exc, (ConnectionError, TimeoutError))
            )
            if retryable and attempt < config.RETRY_ATTEMPTS:
                time.sleep(delay)
                delay *= 2  # 3s, then 6s
                continue
            raise friendly_error(provider, exc) from exc