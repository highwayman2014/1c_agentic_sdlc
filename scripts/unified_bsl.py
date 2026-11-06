"""Select a shared BSL workspace; enable providers only for explicitly approved sources."""
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


def available_memory_mib():
    if os.name == 'nt':
        import ctypes
        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                        *[(name, ctypes.c_ulonglong) for name in
                          ('total_phys', 'avail_phys', 'total_page', 'avail_page', 'total_virtual', 'avail_virtual', 'avail_extended')]]
        status = Status(); status.length = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ValueError('Cannot verify available memory before workspace launch')
        return status.avail_phys // (1024 * 1024)
    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') // (1024 * 1024)
    except (ValueError, OSError, AttributeError):
        raise ValueError('Memory admission is not implemented on this platform')


def workspace_setting(runtime, name, source, default=None):
    for declared, value in runtime.get(name, {}).items():
        if Path(declared).resolve() == source:
            return value
    return default


def configure(runtime, inherited, repository, *, lexical_only=False):
    from onec_runtime import configure as live_configure
    from mcp_profile import enforce_baseline_launch_policy, read_env, validate_embedding_snapshot

    env = {k: v for k, v in inherited.items()
           if not k.startswith(("EMBEDDING_", "BSL_MCP_EFFECTIVE_EMBEDDING_"))}
    source = workspace_from_environment(env)
    provider_settings = {}
    if source is not None:
        # Parse before reading credentials or starting the executable.
        project_config = tomllib.loads((source / "bsl-analyzer.toml").read_text(encoding="utf-8-sig"))
        mode = enforce_baseline_launch_policy(["--profile", "workspace", "--source-dir", str(source)])
        minimum = workspace_setting(runtime, 'unified_workspace_min_available_mib', source, 0)
        if minimum:
            available = available_memory_mib()
            if available < minimum:
                raise ValueError(f'Workspace launch blocked by memory budget: available {available} MiB, required {minimum} MiB. Indexes retained; free memory before reconnecting.')
        if mode == "embeddings-enabled" and not lexical_only:
            validate_embedding_snapshot(source, project_config)
            settings = {**runtime["embedding_defaults"], **runtime.get("unified_embedding_defaults", {}),
                        **read_env(runtime["embedding_file"])}
            provider_settings = {key: value for key, value in settings.items() if key.startswith("EMBEDDING_")}
            if not provider_settings.get("EMBEDDING_API_KEY"):
                raise ValueError("Approved embedding source has no private provider credential")
            provider_settings.setdefault("EMBEDDING_CONCURRENCY", "1")
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
    # The live-only builder strips provider settings by design; restore only the approved set.
    env.update(provider_settings)
    if source is not None:
        command[command.index("--source-dir") + 1] = str(source)
        command[command.index("--mode") + 1] = "broker"
        cache = workspace_setting(runtime, 'unified_workspace_caches', source, runtime['unified_cache'])
        command[command.index("--cache-dir") + 1] = cache
        command.extend(["--enable-tool", "references"])
        env.setdefault("BSL_MCP_IDLE_TTL_SECS", "43200")
        env.setdefault("BSL_MCP_DAEMON_LOG", "1")
    if Path(runtime["platform_help"]).is_dir():
        env["BSL_PLATFORM_HELP_CORPUS"] = runtime["platform_help"]
    return command, env
