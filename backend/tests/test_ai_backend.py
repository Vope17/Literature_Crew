import json
import os
import subprocess
from pathlib import Path

import pytest

import ai_backend
from ai_backend import AIBackendError, cli_environment, get_settings, require_cli_login, run_cli


@pytest.fixture(autouse=True)
def cli_on_path(monkeypatch):
    monkeypatch.setattr(ai_backend.shutil, "which", lambda executable: f"/usr/bin/{executable}")


@pytest.mark.parametrize("backend", ["codex_cli", "claude_cli"])
def test_cli_settings_ignore_api_key_and_api_model(monkeypatch, backend):
    monkeypatch.setenv("AI_BACKEND", backend)
    monkeypatch.setenv("MODEL", "openai/api-model")
    monkeypatch.setenv("OPENAI_API_KEY", "private-server-key")
    monkeypatch.delenv("CLI_MODEL", raising=False)
    settings = get_settings()
    assert settings.model == settings.api_key == ""
    assert settings.public_config()["ready"] is True
    assert settings.public_config()["model"] == "CLI default"
    assert "private-server-key" not in str(settings.public_config())


def test_missing_cli_and_unknown_backend_have_actionable_setup_errors(monkeypatch):
    monkeypatch.setenv("AI_BACKEND", "codex_cli")
    monkeypatch.setattr(ai_backend.shutil, "which", lambda _: None)
    assert get_settings().public_config()["ready"] is False
    assert "Install" in get_settings().setup_error()
    monkeypatch.setenv("AI_BACKEND", "invalid")
    assert "AI_BACKEND" in get_settings().setup_error()


def test_cli_environment_does_not_inherit_api_billing_credentials(monkeypatch):
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(name, "secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "owned-by-cli")
    env = cli_environment()
    assert not any(name in env for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY"))
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "owned-by-cli"
    assert os.environ["OPENAI_API_KEY"] == "secret"


def test_codex_uses_stdin_schema_and_final_output_file(monkeypatch):
    seen = {}
    prompt = 'Paper text: $(cat secrets); "do something"'

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        schema = Path(command[command.index("--output-schema") + 1])
        assert json.loads(schema.read_text()) == {"type": "object"}
        Path(command[command.index("--output-last-message") + 1]).write_text('{"papers": []}')
        return "Progress output that must not become the result"

    monkeypatch.setattr(ai_backend, "_run", run)
    assert run_cli("codex_cli", prompt, schema={"type": "object"}) == '{"papers": []}'
    assert seen["prompt"] == prompt and prompt not in seen["command"]
    assert seen["command"][-1] == "-"
    assert seen["command"][seen["command"].index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in seen["command"]
    assert "shell_tool" in seen["command"] and "multi_agent" in seen["command"]
    assert not Path(seen["cwd"]).exists()


def test_claude_disables_tools_and_reads_structured_result(monkeypatch):
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return json.dumps({"is_error": False, "structured_output": {"papers": []}})

    monkeypatch.setattr(ai_backend, "_run", run)
    assert json.loads(run_cli("claude_cli", "Evidence", schema={"type": "object"})) == {"papers": []}
    command = seen["command"]
    assert command[command.index("--tools") + 1] == ""
    assert "--no-session-persistence" in command and "--strict-mcp-config" in command
    assert "--bare" not in command  # Bare mode does not use subscription login.


@pytest.mark.parametrize("output", ['{"is_error": true, "result": "private-token"}', "not JSON", "[]"])
def test_claude_error_output_is_not_exposed(monkeypatch, output):
    monkeypatch.setattr(ai_backend, "_run", lambda *args, **kwargs: output)
    with pytest.raises(AIBackendError) as error:
        run_cli("claude_cli", "Evidence")
    assert "private-token" not in str(error.value)


@pytest.mark.parametrize("backend, status", [
    ("codex_cli", "Logged in using an API key"),
    ("claude_cli", '{"authMethod":"api_key","loggedIn":true}'),
])
def test_subscription_modes_reject_api_billing_login(monkeypatch, backend, status):
    monkeypatch.setattr(ai_backend, "_run", lambda *args, **kwargs: status)
    with pytest.raises(AIBackendError, match="subscription"):
        require_cli_login(backend)


@pytest.mark.parametrize("backend, status", [
    ("codex_cli", "Logged in using ChatGPT"),
    ("claude_cli", '{"authMethod":"claude.ai","loggedIn":true}'),
])
def test_subscription_login_is_checked_via_official_cli(monkeypatch, backend, status):
    monkeypatch.setattr(ai_backend, "_run", lambda *args, **kwargs: status)
    require_cli_login(backend)


def test_subprocess_failure_does_not_expose_cli_output(monkeypatch, tmp_path):
    class Process:
        returncode = 1

        def communicate(self, **kwargs):
            return "private stdout", "private stderr"

    monkeypatch.setattr(ai_backend.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(AIBackendError) as error:
        ai_backend._run(["cli"], cwd=str(tmp_path))
    assert "private" not in str(error.value)


def test_timed_out_cli_process_group_is_stopped(monkeypatch, tmp_path):
    killed = []

    class Process:
        pid = 12345
        calls = 0

        def communicate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("cli", 1)
            return "", ""

        def kill(self):
            killed.append(self.pid)

    monkeypatch.setattr(ai_backend.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(ai_backend.os, "killpg", lambda pid, sig: killed.append(pid))
    with pytest.raises(AIBackendError, match="timed out"):
        ai_backend._run(["cli"], cwd=str(tmp_path), timeout=1)
    assert killed == [12345]
