"""Device sign-in through the official Codex app-server, without handling tokens."""

import asyncio
import json
import re
import shutil
import time
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from ai_backend import AIBackendError, cli_environment

LOGIN_ERROR = "ChatGPT sign-in failed. Check your connection and enable device code login in ChatGPT security settings or workspace permissions, then retry."


class ChatGPTLogin:
    def __init__(self):
        self.process = None
        self.directory = None
        self.reader = None
        self.expiry = None
        self.pending = {}
        self.counter = 0
        self.boot_lock = asyncio.Lock()
        self.action_lock = asyncio.Lock()
        self.state = {"status": "disconnected"}
        self.completed = {}

    async def _boot(self):
        async with self.boot_lock:
            if self.process is not None and self.process.returncode is None and self.reader is not None and not self.reader.done():
                return
            await self.close()
            binary = shutil.which("codex")
            if not binary:
                raise AIBackendError("Install the official Codex CLI on the backend to connect ChatGPT.")
            self.directory = TemporaryDirectory(prefix="literature-signin-")
            try:
                self.process = await asyncio.create_subprocess_exec(
                    binary, "app-server", cwd=self.directory.name, env=cli_environment(),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, limit=1024 * 1024,
                )
                self.reader = asyncio.create_task(self._read())
                await self._request("initialize", {"clientInfo": {
                    "name": "literature_crew", "title": "Literature Crew", "version": "0.1.0",
                }})
                await self._send({"method": "initialized"})
            except Exception:
                await self.close()
                raise AIBackendError("Cannot initialize Codex sign-in. Check the installed CLI version and connection.") from None

    async def _send(self, message):
        if self.process is None or self.process.returncode is not None:
            raise AIBackendError("Codex sign-in stopped. Please reconnect.")
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def _request(self, method, params=None):
        self.counter += 1
        request_id = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self._send({"id": request_id, "method": method, "params": params or {}})
            return await asyncio.wait_for(future, 20)
        except (asyncio.TimeoutError, OSError):
            raise AIBackendError("Codex sign-in did not respond. Check your connection and retry.") from None
        finally:
            self.pending.pop(request_id, None)

    def _finish(self, params):
        if self.state.get("login_id") != params.get("loginId"):
            return
        if self.expiry is not None:
            self.expiry.cancel()
            self.expiry = None
        self.state = {"status": "connected"} if params.get("success") is True else {
            "status": "failed", "message": LOGIN_ERROR,
        }

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if not isinstance(message, dict):
                    continue
                future = self.pending.get(message.get("id"))
                if future is not None and not future.done():
                    if "error" in message:
                        future.set_exception(AIBackendError(LOGIN_ERROR))
                    else:
                        future.set_result(message.get("result", {}))
                elif message.get("method") == "account/login/completed":
                    params = message.get("params") or {}
                    self.completed[params.get("loginId")] = {"loginId": params.get("loginId"), "success": params.get("success")}
                    if len(self.completed) > 8:
                        self.completed.pop(next(iter(self.completed)))
                    self._finish(params)
        except (ValueError, OSError):
            pass
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(AIBackendError("Codex sign-in stopped. Please reconnect."))
            if self.state["status"] == "pending":
                self.state = {"status": "failed", "message": "Codex sign-in stopped. Please reconnect."}

    async def _account(self):
        result = await self._request("account/read", {"refreshToken": False})
        account = result.get("account") or {}
        # Whitelist public account fields. Never return raw RPC responses.
        return {"connected": account.get("type") == "chatgpt",
                "plan": account.get("planType") if isinstance(account.get("planType"), str) else None}

    def _public(self, account):
        state = {key: self.state[key] for key in ("status", "verification_url", "user_code", "expires_at", "message") if key in self.state}
        state["connected"] = account["connected"]
        state["plan"] = account["plan"]
        if account["connected"] and state["status"] != "pending":
            state = {"status": "connected", **account}
        elif not account["connected"] and state["status"] == "connected":
            state["status"] = "disconnected"
        return state

    async def status(self):
        async with self.action_lock:
            await self._boot()
            return self._public(await self._account())

    async def models(self):
        async with self.action_lock:
            await self._boot()
            if not (await self._account())["connected"]:
                raise AIBackendError("Connect your ChatGPT subscription before loading models.")
            models = {}
            cursor = None
            seen = set()
            while True:
                params = {"limit": 100, "includeHidden": False}
                if cursor:
                    params["cursor"] = cursor
                result = await self._request("model/list", params)
                for item in result.get("data", []):
                    model_id = item.get("model") or item.get("id")
                    if isinstance(model_id, str) and not item.get("hidden") and "text" in item.get("inputModalities", ["text"]):
                        models[model_id] = {"id": model_id, "name": item.get("displayName") or model_id}
                cursor = result.get("nextCursor")
                if not cursor:
                    return list(models.values())
                if cursor in seen:
                    raise AIBackendError("Codex returned an invalid model catalog. Please refresh models.")
                seen.add(cursor)

    async def start(self):
        async with self.action_lock:
            await self._boot()
            account = await self._account()
            if account["connected"] or self.state["status"] == "pending":
                return self._public(account)
            result = await self._request("account/login/start", {"type": "chatgptDeviceCode"})
            url = result.get("verificationUrl", "")
            parsed = urlsplit(url)
            code = result.get("userCode", "")
            login_id = result.get("loginId")
            if (parsed.scheme != "https" or parsed.netloc != "auth.openai.com"
                    or parsed.path != "/codex/device" or parsed.query or parsed.fragment
                    or not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9-]{4,64}", code)
                    or not isinstance(login_id, str) or not login_id):
                await self.close()
                raise AIBackendError("Codex returned an unsupported sign-in response. Update the official CLI and retry.")
            self.state = {"status": "pending", "login_id": login_id,
                          "verification_url": url, "user_code": code, "expires_at": time.time() + 900}
            self.expiry = asyncio.create_task(self._expire(login_id))
            if login_id in self.completed:
                self._finish(self.completed[login_id])
                account = await self._account()
            return self._public(account)

    async def _expire(self, login_id):
        await asyncio.sleep(900)
        async with self.action_lock:
            if self.state.get("login_id") == login_id:
                self.expiry = None
                try:
                    await self._request("account/login/cancel", {"loginId": login_id})
                except AIBackendError:
                    pass
                self.state = {"status": "expired", "message": "Sign-in expired. Please start again."}

    async def cancel(self):
        async with self.action_lock:
            if self.state["status"] == "pending":
                try:
                    await self._request("account/login/cancel", {"loginId": self.state["login_id"]})
                finally:
                    if self.expiry is not None:
                        self.expiry.cancel()
                        self.expiry = None
                    self.state = {"status": "disconnected"}
            return self._public(await self._account()) if self.process is not None else {"status": "disconnected", "connected": False, "plan": None}

    async def close(self):
        if self.expiry is not None:
            self.expiry.cancel()
            self.expiry = None
        if self.process is not None:
            if self.process.returncode is None:
                self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            self.process = None
        if self.reader is not None:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
            self.reader = None
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None
        self.completed.clear()
        self.state = {"status": "disconnected"}
