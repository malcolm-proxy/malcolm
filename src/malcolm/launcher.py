from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Mapping

import uvicorn

from malcolm.app import create_app
from malcolm.cli import LaunchClaudeOptions
from malcolm.config import Settings


CLAUDE_BINARY = "claude"
_STARTUP_TIMEOUT_SECONDS = 10.0
_SHUTDOWN_TIMEOUT_SECONDS = 5.0
_POLL_INTERVAL_SECONDS = 0.05


def _build_claude_env(
    settings: Settings,
    opts: LaunchClaudeOptions,
    base_env: Mapping[str, str],
) -> dict[str, str]:
    env = dict(base_env)
    env["ANTHROPIC_BASE_URL"] = f"http://{settings.host}:{settings.port}"
    if opts.anthropic_api_key is not None:
        env["ANTHROPIC_API_KEY"] = opts.anthropic_api_key
    if opts.anthropic_auth_token is not None:
        env["ANTHROPIC_AUTH_TOKEN"] = opts.anthropic_auth_token
    return env


def _build_claude_argv(opts: LaunchClaudeOptions) -> list[str]:
    argv = [CLAUDE_BINARY]
    if opts.model is not None:
        argv += ["--model", opts.model]
    return argv


def _build_silent_server(settings: Settings) -> uvicorn.Server:
    config = uvicorn.Config(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="critical",
        access_log=False,
    )
    return uvicorn.Server(config)


def _wait_until_started(
    server: uvicorn.Server,
    thread: threading.Thread,
    timeout: float = _STARTUP_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if getattr(server, "started", False):
            return
        if not thread.is_alive():
            raise RuntimeError(
                "uvicorn failed to start "
                f"(host={server.config.host} port={server.config.port}) — "
                "is the port already in use?"
            )
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"uvicorn did not become ready within {timeout:.1f}s"
    )


def launch_with_claude(settings: Settings, opts: LaunchClaudeOptions) -> int:
    env = _build_claude_env(settings, opts, os.environ)
    argv = _build_claude_argv(opts)
    server = _build_silent_server(settings)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        try:
            _wait_until_started(server, thread)
        except (RuntimeError, TimeoutError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        try:
            return subprocess.run(argv, env=env).returncode
        except FileNotFoundError:
            print(
                f"error: '{CLAUDE_BINARY}' binary not found on PATH — "
                "install Claude Code first",
                file=sys.stderr,
            )
            return 127
    finally:
        server.should_exit = True
        thread.join(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
