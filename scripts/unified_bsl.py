"""Select a workspace for the shared BSL MCP without enabling embedding providers."""
import os
from pathlib import Path
import tomllib


def workspace_from_environment(env):
    start = Path(env.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / "bsl-analyzer.toml").is_file():
            return candidate
        if (candidate / ".git").exists():
            break
    return None


def configure(runtime, inherited, repository):
    from onec_runtime import configure as live_configure
    from mcp_profile import enforce_baseline_launch_policy

    env = {k: v for k, v in inherited.items()
           if not k.startswith(("EMBEDDING_", "BSL_MCP_EFFECTIVE_EMBEDDING_"))}
    source = workspace_from_environment(env)
    if source is not None:
        # Parse before reading credentials or starting the executable.
        tomllib.loads((source / "bsl-analyzer.toml").read_text(encoding="utf-8-sig"))
        enforce_baseline_launch_policy(["--profile", "workspace", "--source-dir", str(source)])
    runtime = dict(runtime)
    if runtime.get("broker_current"):
        pointer = Path(runtime["broker_current"])
        name = pointer.read_text(encoding="utf-8").strip()
        if not name.startswith("bsl-analyzer-") or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Invalid shared analyzer version pointer")
        application = pointer.parent / name
        if not application.is_file():
            raise ValueError("Shared analyzer version is not installed")
        runtime["broker_application"] = str(application)
    command, env = live_configure(runtime, env)
    if source is not None:
        command[command.index("--source-dir") + 1] = str(source)
        command[command.index("--mode") + 1] = "broker"
        command[command.index("--cache-dir") + 1] = runtime["unified_cache"]
        command.extend(["--enable-tool", "references"])
        env.setdefault("BSL_MCP_IDLE_TTL_SECS", "43200")
        env.setdefault("BSL_MCP_DAEMON_LOG", "1")
    if Path(runtime["platform_help"]).is_dir():
        env["BSL_PLATFORM_HELP_CORPUS"] = runtime["platform_help"]
    return command, env
