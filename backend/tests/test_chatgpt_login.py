import asyncio
import sys

import pytest

import chatgpt_login
from ai_backend import AIBackendError
from chatgpt_login import ChatGPTLogin


def test_rpc_transport_initializes_and_filters_account_fields(monkeypatch, tmp_path):
    script = tmp_path / "codex"
    script.write_text(f"#!{sys.executable}\n" + '''import json, sys
initialized = False
for line in sys.stdin:
    message = json.loads(line)
    if message['method'] == 'initialized':
        initialized = True
        continue
    if message['method'] == 'initialize':
        result = {'userAgent':'test'}
    elif message['method'] == 'account/read' and initialized:
        result = {'account': {'type':'chatgpt', 'planType':'plus', 'accessToken':'DO-NOT-EXPOSE', 'email':'private@example.com'}}
    else:
        raise RuntimeError('unexpected request')
    print(json.dumps({'id':message['id'], 'result':result}), flush=True)
''')
    script.chmod(0o755)
    monkeypatch.setattr(chatgpt_login.shutil, "which", lambda _: str(script))

    async def exercise():
        login = ChatGPTLogin()
        try:
            result = await login.status()
            assert result == {"status": "connected", "connected": True, "plan": "plus"}
            assert "DO-NOT-EXPOSE" not in str(result) and "private@example" not in str(result)
        finally:
            await login.close()
        assert login.process is None

    asyncio.run(exercise())


def fake_login(monkeypatch, *, url="https://auth.openai.com/codex/device"):
    login = ChatGPTLogin()

    async def boot():
        pass

    async def request(method, params=None):
        if method == "account/read":
            return {"account": None}
        if method == "account/login/start":
            return {"loginId": "owned-by-cli", "verificationUrl": url, "userCode": "ABCD-1234", "accessToken": "private"}
        return {}

    monkeypatch.setattr(login, "_boot", boot)
    monkeypatch.setattr(login, "_request", request)
    return login


def test_device_code_flow_is_idempotent_and_cancellable(monkeypatch):
    async def exercise():
        login = fake_login(monkeypatch)
        try:
            first = await login.start()
            second = await login.start()
            assert first == second
            assert first["status"] == "pending" and first["user_code"] == "ABCD-1234"
            assert "login_id" not in first and "accessToken" not in first
            assert (await login.cancel())["status"] == "disconnected"
            assert login.expiry is None and "user_code" not in login.state
        finally:
            await login.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("url", ["https://evil.example/codex/device", "http://auth.openai.com/codex/device", "https://auth.openai.com/codex/device?token=private"])
def test_untrusted_authorization_urls_are_rejected(monkeypatch, url):
    async def exercise():
        login = fake_login(monkeypatch, url=url)
        with pytest.raises(AIBackendError, match="unsupported"):
            await login.start()
        assert "user_code" not in login.state
    asyncio.run(exercise())


def test_completion_clears_codes_and_does_not_expose_provider_errors(monkeypatch):
    async def exercise():
        login = fake_login(monkeypatch)
        try:
            await login.start()
            login._finish({"loginId": "other-attempt", "success": True})
            assert login.state["status"] == "pending"
            login._finish({"loginId": "owned-by-cli", "success": False, "error": "private-token"})
            assert login.state["status"] == "failed"
            assert "private-token" not in str(login.state) and "user_code" not in login.state
            assert login.expiry is None
        finally:
            await login.close()
    asyncio.run(exercise())


def test_device_code_expiry_cancels_official_login(monkeypatch):
    async def exercise():
        login = fake_login(monkeypatch)
        try:
            await login.start()
            login.expiry.cancel()
            await asyncio.gather(login.expiry, return_exceptions=True)
            login.expiry = None

            async def no_wait(_):
                pass

            monkeypatch.setattr(chatgpt_login.asyncio, "sleep", no_wait)
            await login._expire("owned-by-cli")
            assert login.state["status"] == "expired" and "user_code" not in login.state
        finally:
            await login.close()
    asyncio.run(exercise())


def test_subscription_catalog_paginates_and_filters_hidden_and_nontext_models(monkeypatch):
    async def exercise():
        login = fake_login(monkeypatch)
        calls = []

        async def request(method, params=None):
            if method == 'account/read':
                return {'account': {'type': 'chatgpt'}}
            calls.append(params)
            if params.get('cursor') == 'next':
                return {'data': [{'id': 'record-id', 'model': 'native-model', 'displayName': 'Native Model'}], 'nextCursor': None}
            return {'data': [{'id': 'hidden', 'hidden': True}, {'id': 'image-only', 'inputModalities': ['image']}], 'nextCursor': 'next'}

        monkeypatch.setattr(login, '_request', request)
        assert await login.models() == [{'id': 'native-model', 'name': 'Native Model'}]
        assert calls[1]['cursor'] == 'next'
        await login.close()
    asyncio.run(exercise())
