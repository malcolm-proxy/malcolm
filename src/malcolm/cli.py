import argparse
import logging
import os
import sys
from dataclasses import dataclass

import uvicorn

from malcolm.app import create_app
from malcolm.config import Settings


_SETTINGS_FIELDS = {
    "target_url",
    "target_api_key",
    "host",
    "port",
    "storage_enabled",
    "db_path",
    "log_level",
    "config_file",
}

DEFAULT_LAUNCH_CLAUDE_TARGET_URL = "https://api.anthropic.com/v1"


@dataclass(frozen=True)
class LaunchClaudeOptions:
    enabled: bool
    model: str | None
    anthropic_api_key: str | None
    anthropic_auth_token: str | None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="malcolm",
        description="LLM API monitoring proxy",
    )
    parser.add_argument("--malcolm-target-url", dest="target_url")
    parser.add_argument("--malcolm-target-api-key", dest="target_api_key")
    parser.add_argument("--malcolm-host", dest="host")
    parser.add_argument("--malcolm-port", dest="port", type=int)
    parser.add_argument("--malcolm-storage-enabled", dest="storage_enabled")
    parser.add_argument("--malcolm-db-path", dest="db_path")
    parser.add_argument("--malcolm-log-level", dest="log_level")
    parser.add_argument("--malcolm-config-file", dest="config_file")

    parser.add_argument("--launch-claude", dest="launch_claude", action="store_true")
    parser.add_argument("--model", dest="model", default=argparse.SUPPRESS)
    parser.add_argument(
        "--anthropic-api-key", dest="anthropic_api_key", default=argparse.SUPPRESS
    )
    parser.add_argument(
        "--anthropic-auth-token", dest="anthropic_auth_token", default=argparse.SUPPRESS
    )
    return parser


def _parse_cli() -> tuple[dict, LaunchClaudeOptions]:
    args = _build_parser().parse_args()
    overrides = {
        k: v
        for k, v in vars(args).items()
        if k in _SETTINGS_FIELDS and v is not None
    }
    launch = LaunchClaudeOptions(
        enabled=getattr(args, "launch_claude", False),
        model=getattr(args, "model", None),
        anthropic_api_key=getattr(args, "anthropic_api_key", None),
        anthropic_auth_token=getattr(args, "anthropic_auth_token", None),
    )
    return overrides, launch


def _parse_args() -> dict:
    overrides, _ = _parse_cli()
    return overrides


def _parse_tui_args() -> str | None:
    parser = argparse.ArgumentParser(prog="malcolm tui", description="TUI log viewer")
    parser.add_argument("--db-path", default=None, help="Path to the SQLite database")
    args = parser.parse_args(sys.argv[2:])
    return args.db_path


def _apply_launch_defaults(overrides: dict, env: dict | None = None) -> dict:
    """Inject the Anthropic default target URL when neither CLI nor env supplies one."""
    env = os.environ if env is None else env
    if "target_url" not in overrides and not env.get("MALCOLM_TARGET_URL"):
        return {**overrides, "target_url": DEFAULT_LAUNCH_CLAUDE_TARGET_URL}
    return overrides


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "tui":
        from malcolm.tui import run_tui

        run_tui(db_path=_parse_tui_args())
        return

    overrides, launch = _parse_cli()

    if launch.enabled:
        overrides = _apply_launch_defaults(overrides)
        settings = Settings(**overrides)
        logging.basicConfig(level=logging.CRITICAL)
        from malcolm.launcher import launch_with_claude

        sys.exit(launch_with_claude(settings, launch))
        return

    settings = Settings(**overrides)

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
