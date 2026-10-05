"""Discover text-generation model IDs using the user's OpenAI credentials."""

import re

from openai import OpenAI


def is_text_model(model_id: str) -> bool:
    # /models has no capability fields. Filter known non-text/specialized families
    # by name, rather than maintaining a static allowlist of individual models.
    base = model_id.split(":")[1] if model_id.startswith("ft:") else model_id
    return bool(re.match(r"^(gpt-|chatgpt-|o\d)", base)) and not any(
        word in base for word in (
            "audio", "realtime", "transcribe", "tts", "image", "instruct",
            "search", "deep-research", "embedding", "moderation",
        )
    )


def list_models(api_key: str) -> list[dict[str, str]]:
    with OpenAI(api_key=api_key, timeout=20, max_retries=1) as client:
        ids = sorted({model.id for model in client.models.list() if is_text_model(model.id)})
    return [{"id": f"openai/{model_id}", "name": model_id} for model_id in ids]
