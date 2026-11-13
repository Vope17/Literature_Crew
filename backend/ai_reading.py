"""Structured text/vision calls shared by page reading and evidence reduction."""

import base64

from openai import OpenAI

from ai_backend import AIBackendError, run_cli


def read_structured(prompt, schema, settings, *, images=None):
    try:
        if settings.backend != "openai_api":
            raw = run_cli(settings.backend, prompt, model=settings.model,
                          schema=schema.model_json_schema(), timeout=settings.timeout,
                          images=images)
            return schema.model_validate_json(raw)
        content = [{"type": "input_text", "text": prompt}]
        content.extend({"type": "input_image", "detail": "high",
                        "image_url": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}
                       for data in images or [])
        with OpenAI(api_key=settings.api_key, timeout=120, max_retries=0) as client:
            response = client.responses.parse(
                model=settings.model.removeprefix("openai/"),
                input=[{"role": "user", "content": content}],
                text_format=schema, store=False,
            )
        if response.status != "completed" or response.output_parsed is None:
            raise ValueError("Incomplete or refused reading")
        return schema.model_validate(response.output_parsed)
    except AIBackendError:
        raise
    except Exception:
        raise AIBackendError(
            "Document analysis failed. Select a model supporting images and structured output, "
            "and check your AI connection and quota. No unread batch was treated as complete."
        ) from None
