import sys

from malcolm.cli import (
    DEFAULT_LAUNCH_CLAUDE_TARGET_URL,
    _apply_launch_defaults,
    _parse_args,
    _parse_cli,
)


def test_parse_no_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["malcolm"])
    assert _parse_args() == {}


def test_parse_target_url(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["malcolm", "--malcolm-target-url=http://localhost:11434/v1"])
    result = _parse_args()
    assert result == {"target_url": "http://localhost:11434/v1"}


def test_parse_multiple_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "malcolm",
        "--malcolm-target-url=http://localhost:11434/v1",
        "--malcolm-port=9000",
        "--malcolm-config-file=custom.yaml",
    ])
    result = _parse_args()
    assert result == {
        "target_url": "http://localhost:11434/v1",
        "port": 9000,
        "config_file": "custom.yaml",
    }


def test_cli_args_override_env(monkeypatch):
    monkeypatch.setenv("MALCOLM_TARGET_URL", "http://from-env.com")
    monkeypatch.setenv("MALCOLM_PORT", "8900")
    monkeypatch.setattr(sys, "argv", ["malcolm", "--malcolm-port=9999"])

    from malcolm.config import Settings

    overrides = _parse_args()
    settings = Settings(**overrides)

    assert settings.target_url == "http://from-env.com"  # from env
    assert settings.port == 9999  # overridden by CLI


def test_parse_launch_claude_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["malcolm", "--launch-claude"])
    overrides, launch = _parse_cli()
    assert overrides == {}
    assert launch.enabled is True
    assert launch.model is None
    assert launch.anthropic_api_key is None
    assert launch.anthropic_auth_token is None


def test_parse_launch_claude_with_model(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["malcolm", "--launch-claude", "--model", "gpt-4.1"]
    )
    _, launch = _parse_cli()
    assert launch.enabled is True
    assert launch.model == "gpt-4.1"


def test_parse_anthropic_keys_distinguish_unset_vs_empty(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["malcolm", "--launch-claude", "--anthropic-api-key="],
    )
    _, launch = _parse_cli()
    assert launch.anthropic_api_key == ""
    assert launch.anthropic_auth_token is None


def test_parse_anthropic_auth_token_passed(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["malcolm", "--launch-claude", "--anthropic-auth-token=ollama"],
    )
    _, launch = _parse_cli()
    assert launch.anthropic_auth_token == "ollama"


def test_parse_launch_flags_not_in_settings_overrides(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "malcolm",
            "--launch-claude",
            "--model=gpt-4.1",
            "--anthropic-api-key=dummy",
            "--anthropic-auth-token=dummy",
            "--malcolm-port=9000",
        ],
    )
    overrides, launch = _parse_cli()
    assert overrides == {"port": 9000}
    assert launch.enabled is True
    assert launch.model == "gpt-4.1"


def test_apply_launch_defaults_when_no_url():
    overrides = _apply_launch_defaults({}, env={})
    assert overrides == {"target_url": DEFAULT_LAUNCH_CLAUDE_TARGET_URL}


def test_apply_launch_defaults_skipped_when_env_set():
    overrides = _apply_launch_defaults(
        {}, env={"MALCOLM_TARGET_URL": "http://from-env.com"}
    )
    assert overrides == {}


def test_apply_launch_defaults_skipped_when_cli_set():
    overrides = _apply_launch_defaults(
        {"target_url": "http://from-cli.com"}, env={}
    )
    assert overrides == {"target_url": "http://from-cli.com"}


def test_apply_launch_defaults_does_not_mutate_input():
    original = {}
    _apply_launch_defaults(original, env={})
    assert original == {}
