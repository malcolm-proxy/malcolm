import threading
import time
from types import SimpleNamespace

import pytest

from malcolm.cli import LaunchClaudeOptions
from malcolm.launcher import (
    _build_claude_argv,
    _build_claude_env,
    _wait_until_started,
    launch_with_claude,
)


def _opts(**kwargs) -> LaunchClaudeOptions:
    base = dict(
        enabled=True,
        model=None,
        anthropic_api_key=None,
        anthropic_auth_token=None,
    )
    base.update(kwargs)
    return LaunchClaudeOptions(**base)


def _fake_settings(host: str = "127.0.0.1", port: int = 8900):
    return SimpleNamespace(host=host, port=port)


# --- env builder ---------------------------------------------------------


def test_build_claude_env_base_url_always_set():
    env = _build_claude_env(_fake_settings("0.0.0.0", 9000), _opts(), {})
    assert env["ANTHROPIC_BASE_URL"] == "http://0.0.0.0:9000"


def test_build_claude_env_api_key_present():
    env = _build_claude_env(
        _fake_settings(), _opts(anthropic_api_key="sk-test"), {}
    )
    assert env["ANTHROPIC_API_KEY"] == "sk-test"


def test_build_claude_env_api_key_empty_string_passed_through():
    env = _build_claude_env(
        _fake_settings(),
        _opts(anthropic_api_key=""),
        {"ANTHROPIC_API_KEY": "from-shell"},
    )
    assert env["ANTHROPIC_API_KEY"] == ""


def test_build_claude_env_api_key_none_inherits():
    env = _build_claude_env(
        _fake_settings(),
        _opts(anthropic_api_key=None),
        {"ANTHROPIC_API_KEY": "from-shell"},
    )
    assert env["ANTHROPIC_API_KEY"] == "from-shell"


def test_build_claude_env_api_key_none_absent_when_not_inherited():
    env = _build_claude_env(_fake_settings(), _opts(anthropic_api_key=None), {})
    assert "ANTHROPIC_API_KEY" not in env


def test_build_claude_env_auth_token_independent():
    env = _build_claude_env(
        _fake_settings(), _opts(anthropic_auth_token="ollama"), {}
    )
    assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama"
    assert "ANTHROPIC_API_KEY" not in env


def test_build_claude_env_inherits_unrelated_vars():
    base = {"PATH": "/usr/bin", "HOME": "/home/x"}
    env = _build_claude_env(_fake_settings(), _opts(), base)
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/x"


def test_build_claude_env_does_not_mutate_base():
    base = {"PATH": "/usr/bin"}
    _build_claude_env(_fake_settings(), _opts(anthropic_api_key="x"), base)
    assert base == {"PATH": "/usr/bin"}


# --- argv builder --------------------------------------------------------


def test_build_claude_argv_no_model():
    assert _build_claude_argv(_opts()) == ["claude"]


def test_build_claude_argv_with_model():
    assert _build_claude_argv(_opts(model="gpt-4.1")) == [
        "claude",
        "--model",
        "gpt-4.1",
    ]


# --- _wait_until_started -------------------------------------------------


def test_wait_until_started_returns_when_started():
    server = SimpleNamespace(started=True, config=SimpleNamespace(host="x", port=1))

    def loop():
        time.sleep(0.5)

    thread = threading.Thread(target=loop)
    thread.start()
    try:
        _wait_until_started(server, thread, timeout=1.0)  # should return promptly
    finally:
        thread.join()


def test_wait_until_started_timeout():
    server = SimpleNamespace(started=False, config=SimpleNamespace(host="x", port=1))

    def loop():
        time.sleep(2)

    thread = threading.Thread(target=loop)
    thread.start()
    try:
        with pytest.raises(TimeoutError):
            _wait_until_started(server, thread, timeout=0.2)
    finally:
        thread.join()


def test_wait_until_started_thread_dies_early():
    server = SimpleNamespace(
        started=False, config=SimpleNamespace(host="127.0.0.1", port=8900)
    )
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
    with pytest.raises(RuntimeError, match="uvicorn failed to start"):
        _wait_until_started(server, thread, timeout=1.0)


# --- launch_with_claude orchestration -----------------------------------


class _FakeServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8900):
        self.started = False
        self.should_exit = False
        self.config = SimpleNamespace(host=host, port=port)

    def run(self):
        self.started = True
        while not self.should_exit:
            time.sleep(0.01)


def _patch_silent_server(monkeypatch, fake_server):
    monkeypatch.setattr(
        "malcolm.launcher._build_silent_server", lambda settings: fake_server
    )


def _patch_subprocess_run(monkeypatch, returncode=0, capture=None, raises=None):
    def fake_run(argv, env=None):
        if capture is not None:
            capture["argv"] = argv
            capture["env"] = env
        if raises is not None:
            raise raises
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr("malcolm.launcher.subprocess.run", fake_run)


def test_launch_orchestration_end_to_end(monkeypatch):
    fake_server = _FakeServer()
    capture: dict = {}
    _patch_silent_server(monkeypatch, fake_server)
    _patch_subprocess_run(monkeypatch, returncode=0, capture=capture)

    settings = _fake_settings("127.0.0.1", 8900)
    opts = _opts(model="claude-sonnet-4", anthropic_api_key="dummy")

    rc = launch_with_claude(settings, opts)

    assert rc == 0
    assert capture["argv"] == ["claude", "--model", "claude-sonnet-4"]
    assert capture["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8900"
    assert capture["env"]["ANTHROPIC_API_KEY"] == "dummy"
    assert fake_server.should_exit is True


def test_launch_propagates_claude_exit_code(monkeypatch):
    _patch_silent_server(monkeypatch, _FakeServer())
    _patch_subprocess_run(monkeypatch, returncode=42)

    rc = launch_with_claude(_fake_settings(), _opts())
    assert rc == 42


def test_launch_missing_binary_returns_127(monkeypatch, capsys):
    fake_server = _FakeServer()
    _patch_silent_server(monkeypatch, fake_server)
    _patch_subprocess_run(monkeypatch, raises=FileNotFoundError())

    rc = launch_with_claude(_fake_settings(), _opts())

    assert rc == 127
    err = capsys.readouterr().err
    assert "claude" in err and "not found" in err
    assert fake_server.should_exit is True


def test_launch_returns_1_when_uvicorn_fails_to_start(monkeypatch, capsys):
    class _DeadServer:
        def __init__(self):
            self.started = False
            self.should_exit = False
            self.config = SimpleNamespace(host="127.0.0.1", port=8900)

        def run(self):
            return  # exit immediately, never set started

    fake_server = _DeadServer()
    _patch_silent_server(monkeypatch, fake_server)
    # subprocess.run should never be reached
    _patch_subprocess_run(
        monkeypatch, raises=AssertionError("subprocess should not be called")
    )

    rc = launch_with_claude(_fake_settings(), _opts())

    assert rc == 1
    assert "uvicorn failed to start" in capsys.readouterr().err
