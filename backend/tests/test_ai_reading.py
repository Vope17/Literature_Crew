import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import ai_reading
from ai_backend import AISettings, AIBackendError
from pdf_reading import BatchReading, PageReading


def test_openai_sends_ordered_page_images_with_text_and_chosen_model(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    result = BatchReading(pages=[PageReading(page=10, part=1, status="readable", observations=[], limitations="")])
    client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=result)
    monkeypatch.setattr(ai_reading, "OpenAI", lambda **kwargs: client)
    actual = ai_reading.read_structured("Pages 10 and 11", BatchReading,
                                       AISettings("openai_api", "openai/chosen", "test-key"), images=[b"one", b"two"])
    request = client.responses.parse.call_args.kwargs
    assert request["model"] == "chosen" and request["store"] is False
    content = request["input"][0]["content"]
    assert content[0]["text"] == "Pages 10 and 11"
    assert [base64.b64decode(item["image_url"].split(",", 1)[1]) for item in content[1:]] == [b"one", b"two"]
    assert all(item["detail"] == "high" for item in content[1:])
    assert actual == result


@pytest.mark.parametrize("backend", ["codex_cli", "claude_cli"])
def test_cli_reader_passes_images_without_api_billing(monkeypatch, backend):
    def cli(selected, prompt, **kwargs):
        assert selected == backend and kwargs["images"] == [b"image"]
        assert kwargs["model"] == "chosen"
        return '{"pages":[{"page":1,"part":1,"status":"readable","observations":[],"limitations":""}]}'
    monkeypatch.setattr(ai_reading, "run_cli", cli)
    monkeypatch.setattr(ai_reading, "OpenAI", lambda **kw: pytest.fail("Must not call API"))
    ai_reading.read_structured("Read", BatchReading, AISettings(backend, "chosen", ""), images=[b"image"])


def test_vision_provider_error_is_safe_and_does_not_retry_as_text(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.responses.parse.side_effect = RuntimeError("unsupported image secret-key")
    monkeypatch.setattr(ai_reading, "OpenAI", lambda **kwargs: client)
    with pytest.raises(AIBackendError, match="supporting images") as error:
        ai_reading.read_structured("Read", BatchReading, AISettings("openai_api", "example", "secret-key"), images=[b"image"])
    assert "secret-key" not in str(error.value)
    assert client.responses.parse.call_count == 1
