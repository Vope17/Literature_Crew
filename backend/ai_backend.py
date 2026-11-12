"""Server-side API configuration and official, locally authenticated CLI adapters."""

import json
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory


class AIBackendError(RuntimeError):
    """Only application-authored messages may be shown to the user."""


BACKENDS = {
    "openai_api": "OpenAI API",
    "codex_cli": "Codex CLI · ChatGPT subscription",
    "claude_cli": "Claude Code · Claude subscription",
}


@dataclass(frozen=True)
class AISettings:
    backend: str
    model: str
    api_key: str = field(repr=False)
    timeout: int = 600

    def setup_error(self) -> str:
        if self.backend not in BACKENDS:
            return "Set AI_BACKEND to openai_api, codex_cli, or claude_cli in backend/.env."
        if self.backend == "openai_api":
            if not self.api_key:
                return "Set OPENAI_API_KEY in backend/.env and restart the backend first."
            if not self.model:
                return "Set MODEL in backend/.env and restart the backend first."
        else:
            executable = "codex" if self.backend == "codex_cli" else "claude"
            if not shutil.which(executable):
                return f"Install the official {executable} CLI on the backend machine, sign in, then restart the backend."
        return ""

    def public_config(self) -> dict:
        hint = {
            "openai_api": "Set OPENAI_API_KEY and MODEL in backend/.env, then restart the backend.",
            "codex_cli": "Use Connect ChatGPT subscription below to sign in on the official OpenAI page. CLI_MODEL is optional.",
            "claude_cli": "On the backend machine, run claude auth login with your Claude subscription. CLI_MODEL is optional.",
        }.get(self.backend, "Check AI_BACKEND in backend/.env.")
        return {
            "ai_backend": self.backend,
            "ai_label": BACKENDS.get(self.backend, "Unknown AI backend"),
            "model": self.model or ("CLI default" if self.backend != "openai_api" else ""),
            "ready": not bool(self.setup_error()),
            "setup_hint": self.setup_error() or hint,
            "has_api_key": bool(self.api_key) if self.backend == "openai_api" else False,
        }


def get_settings() -> AISettings:
    backend = os.getenv("AI_BACKEND", "openai_api").strip()
    try:
        timeout = int(os.getenv("CLI_TIMEOUT_SECONDS", "600"))
    except ValueError:
        timeout = 600
    return AISettings(
        backend=backend,
        model=os.getenv("MODEL" if backend == "openai_api" else "CLI_MODEL", "").strip(),
        api_key=os.getenv("OPENAI_API_KEY", "").strip() if backend == "openai_api" else "",
        timeout=max(30, min(timeout, 1800)),
    )


def cli_environment() -> dict:
    # A server's API key must not silently replace the user's subscription login.
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(key, None)
    return env


def _run(command: list[str], *, cwd: str, prompt: str = "", timeout: int = 600, include_stderr: bool = False) -> str:
    try:
        process = subprocess.Popen(
            command, cwd=cwd, env=cli_environment(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=os.name == "posix",
        )
    except OSError:
        raise AIBackendError("Cannot start the configured CLI. Check its installation and backend PATH.") from None
    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.communicate()
        raise AIBackendError("The CLI timed out. Try fewer papers or increase CLI_TIMEOUT_SECONDS.") from None
    if process.returncode:
        # CLI output can include account details and credentials; never expose it.
        raise AIBackendError("The CLI failed. Check its login, subscription limits, model access and installed version in your terminal.")
    return stdout + stderr if include_stderr else stdout


def require_cli_login(backend: str) -> None:
    executable = "codex" if backend == "codex_cli" else "claude"
    binary = shutil.which(executable)
    if not binary:
        raise AIBackendError(f"Install the official {executable} CLI on the backend machine and sign in first.")
    with TemporaryDirectory(prefix="literature-auth-") as directory:
        command = [binary, "login", "status"] if backend == "codex_cli" else [binary, "auth", "status"]
        try:
            status = _run(command, cwd=directory, timeout=20, include_stderr=backend == "codex_cli")
        except AIBackendError:
            login = "codex login" if backend == "codex_cli" else "claude auth login"
            raise AIBackendError(f"Check your CLI installation and run {login} on the backend machine to sign in with your subscription.") from None
        if backend == "claude_cli":
            try:
                auth = json.loads(status)
            except (ValueError, TypeError):
                raise AIBackendError("Update Claude Code, then run claude auth login with your subscription.") from None
            if not isinstance(auth, dict) or auth.get("authMethod") not in ("claude.ai", "oauth_token") or auth.get("loggedIn") is False:
                raise AIBackendError("Claude Code must be signed in with your Claude subscription. Run claude auth login.")
        elif "chatgpt" not in status.lower():
            raise AIBackendError("Codex is using API key billing. Run codex login and sign in with ChatGPT for subscription usage.")


def run_cli(backend: str, prompt: str, *, model: str = "", schema: dict | None = None, timeout: int = 600) -> str:
    """Run an unchanged official CLI; credentials stay entirely with that CLI."""
    executable = "codex" if backend == "codex_cli" else "claude"
    binary = shutil.which(executable)
    if binary is None:
        raise AIBackendError(f"The {executable} CLI is not available on the backend PATH.")
    with TemporaryDirectory(prefix="literature-cli-") as directory:
        if backend == "codex_cli":
            output = Path(directory) / "result.txt"
            command = [
                binary, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only", "--color", "never", "--output-last-message", str(output),
                "-c", 'web_search="disabled"',
                "-c", "include_apply_patch_tool=false",
            ]
            for feature in ("shell_tool", "multi_agent", "apps", "hooks", "plugins", "remote_plugin",
                            "browser_use", "in_app_browser", "computer_use", "image_generation", "skill_search"):
                command.extend(["--disable", feature])
            if schema is not None:
                schema_file = Path(directory) / "schema.json"
                schema_file.write_text(json.dumps(schema), encoding="utf-8")
                command.extend(["--output-schema", str(schema_file)])
            if model:
                command.extend(["--model", model])
            command.append("-")
            _run(command, cwd=directory, prompt=prompt, timeout=timeout)
            if not output.exists():
                raise AIBackendError("Codex returned no final response. Check the CLI and selected model.")
            result = output.read_text(encoding="utf-8").strip()
        elif backend == "claude_cli":
            command = [
                binary, "-p", "--output-format", "json", "--no-session-persistence",
                "--tools", "", "--disallowedTools", "mcp__*", "--strict-mcp-config",
                "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "user",
                "--settings", '{"disableAllHooks":true}',
            ]
            if model:
                command.extend(["--model", model])
            if schema is not None:
                command.extend(["--json-schema", json.dumps(schema)])
            output = _run(command, cwd=directory, prompt=prompt, timeout=timeout)
            try:
                payload = json.loads(output)
                if not isinstance(payload, dict) or payload.get("is_error"):
                    raise ValueError("CLI error")
                if schema is not None:
                    structured = payload.get("structured_output")
                    if not isinstance(structured, dict):
                        raise ValueError("No structured output")
                    result = json.dumps(structured)
                else:
                    result = payload.get("result", "")
            except (ValueError, TypeError):
                raise AIBackendError("Claude Code returned an invalid response. Check the CLI version, login and subscription limits.") from None
        else:
            raise AIBackendError("Unsupported CLI backend.")
        if not isinstance(result, str) or not result.strip():
            raise AIBackendError("The CLI returned an empty response. Please retry.")
        return result
