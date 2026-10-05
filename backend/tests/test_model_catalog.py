import httpx
from openai import OpenAI

import model_catalog


def test_lists_models_using_supplied_key_and_filters_specialized_models(monkeypatch):
    ids = ["gpt-4o-mini", "gpt-6-luna", "o3", "gpt-image-1", "gpt-4o-audio-preview",
           "text-embedding-3-small", "whisper-1", "ft:gpt-4o-mini:org:name:id"]

    def handler(request):
        assert request.url.path == "/v1/models"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"object": "list", "data": [
            {"id": name, "object": "model", "created": 0, "owned_by": "test"} for name in ids
        ]})

    monkeypatch.setattr(model_catalog, "OpenAI", lambda **kwargs: OpenAI(
        **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ))
    models = model_catalog.list_models("test-key")
    assert [item["name"] for item in models] == [
        "ft:gpt-4o-mini:org:name:id", "gpt-4o-mini", "gpt-6-luna", "o3",
    ]
    assert all(item["id"] == f"openai/{item['name']}" for item in models)
