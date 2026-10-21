# gemini_client.py
# Gemini has a very large context window, so we use it for whole-repo jobs
# (overview, summaries, build plans). This file wraps the SDK so the rest of
# the code just calls generate() or generate_json().

import json

from google import genai
from google.genai import types

from backend import config
from backend.errors import LLMError
from backend.llm.retry import with_retry

_client = None  # created on first use, so a missing key doesn't crash startup


def _get_client():
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise LLMError("GEMINI_API_KEY is missing. Add it to your .env file and restart the backend.", 500)
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def generate(system: str, prompt: str, json_mode: bool = False) -> str:
    # Low temperature = more factual and less "creative". Good for explaining code.
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.2,
        response_mime_type="application/json" if json_mode else None,
    )

    def call():
        response = _get_client().models.generate_content(
            model=config.GEMINI_MODEL, contents=prompt, config=cfg)
        return response.text or ""

    text = with_retry(call, "Gemini")
    if not text.strip():
        raise LLMError("Gemini returned an empty answer (it may have been blocked). Please try again.")
    return text


def _strip_fences(text: str) -> str:
    # Models sometimes wrap JSON in ```json ... ``` even when told not to.
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def generate_json(system: str, prompt: str):
    # Models occasionally return broken JSON; one retry fixes most cases.
    for attempt in (1, 2):
        text = generate(system, prompt, json_mode=True)
        try:
            return json.loads(_strip_fences(text))
        except json.JSONDecodeError:
            if attempt == 2:
                raise LLMError("Gemini returned malformed data twice. Please try again.")