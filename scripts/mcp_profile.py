"""Run shared MCP installations; read credentials only from local files/environment."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

REPOSITORY = Path(__file__).resolve().parent.parent
ATLASSIAN_KEYS = {
    "JIRA_URL", "JIRA_PERSONAL_TOKEN", "JIRA_USERNAME", "JIRA_API_TOKEN",
    "JIRA_SSL_VERIFY", "CONFLUENCE_URL", "CONFLUENCE_PERSONAL_TOKEN",
    "CONFLUENCE_USERNAME", "CONFLUENCE_API_TOKEN", "CONFLUENCE_SSL_VERIFY",
}


def read_env(path):
    values = {}
    if not Path(path).is_file():
        return values
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError("Invalid local env file: expected NAME=VALUE")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            if value[0] == '"':
                try:
                    value = json.loads(value)
                except ValueError:
                    value = value[1:-1]
            else:
                value = value[1:-1]
        if value:
            values[key.strip()] = value
    return values


def command_for(kind, arguments, runtime, inherited=None, lexical_only=False):
    env = dict(os.environ if inherited is None else inherited)
    if kind == "bsl":
        enforce_baseline_launch_policy(arguments)
        env.update(runtime["embedding_defaults"])
        for key, value in read_env(runtime["embedding_file"]).items():
            if key.startswith("EMBEDDING_") or key == "NAPARNIK_TOKEN":
                env[key] = value
        if lexical_only:
            env = {key: value for key, value in env.items() if not key.startswith("EMBEDDING_")}
        elif not env.get("EMBEDDING_API_KEY"):
            raise ValueError("Set EMBEDDING_API_KEY in the private embedding file, or use --lexical-only")
        if Path(runtime["platform_help"]).is_dir():
            env.setdefault("BSL_PLATFORM_HELP_CORPUS", runtime["platform_help"])
        broker = "--mode" in arguments and arguments[arguments.index("--mode") + 1:][:1] == ["broker"]
        executable = runtime.get("broker_application", runtime["launcher"]) if broker else runtime["launcher"]
        return [executable, *arguments], env
    for key, value in read_env(runtime["atlassian_file"]).items():
        if key in ATLASSIAN_KEYS:
            env[key] = value
    if not (env.get("JIRA_URL") or env.get("CONFLUENCE_URL")):
        raise ValueError("Atlassian credentials are not configured; run configure_mcp.py --apply-shared")
    uvx = shutil.which("uvx")
    if not uvx:
        raise ValueError("uvx is not installed")
    return [uvx, "mcp-atlassian", *arguments], env


def enforce_baseline_launch_policy(arguments, policies=None):
    """Fail before spawning a workspace whose paid embedding policy is unresolved."""
    if "--profile" not in arguments or arguments[arguments.index("--profile") + 1:][:1] != ["workspace"]:
        return
    if "--source-dir" not in arguments:
        raise ValueError("Workspace source directory is required before baseline validation")
    source = Path(arguments[arguments.index("--source-dir") + 1]).resolve()
    registry = REPOSITORY / "mcp/baselines.json"
    if policies is None:
        if not registry.exists():
            return
        policies = json.loads(registry.read_text(encoding="utf-8"))
    for name, policy in policies.items():
        main = Path(policy["source"]).resolve()
        worktrees = Path(policy["worktrees_root"]).resolve()
        if source == main or source.is_relative_to(worktrees):
            if policy["workspace_launch"] != "enabled":
                raise ValueError(f"Workspace MCP paused for {name}: {policy['pause_reason']}")


def run_windows_broker(command, env):
    """Exit promptly on client EOF so pi does not taskkill the detached backend.

    The broker drains Windows named pipes for 2 s; native pi kills a stdio
    process tree after 500 ms. Relay using private pipes so this wrapper can
    exit first while the broker finishes its normal disconnect independently.
    """
    child = subprocess.Popen(command, env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    def trace(message):
        if env.get("BSL_MCP_RELAY_LOG"):
            with open(env["BSL_MCP_RELAY_LOG"], "a", encoding="utf-8") as stream:
                stream.write(f"wrapper={os.getpid()} child={child.pid} {message}\n")
    trace("started")
    input_closed, output_closed = threading.Event(), threading.Event()

    def write_all(fd, data):
        remaining = memoryview(data)
        while remaining:
            remaining = remaining[os.write(fd, remaining):]

    def forward_input():
        try:
            while data := os.read(sys.stdin.fileno(), 65536):
                write_all(child.stdin.fileno(), data)
        except (BrokenPipeError, OSError):
            pass
        finally:
            trace("input EOF")
            child.stdin.close()
            input_closed.set()

    def forward_output():
        try:
            while data := os.read(child.stdout.fileno(), 65536):
                write_all(sys.stdout.fileno(), data)
        except (BrokenPipeError, OSError):
            pass
        finally:
            output_closed.set()

    def forward_stderr():
        try:
            while data := os.read(child.stderr.fileno(), 65536):
                write_all(sys.stderr.fileno(), data)
        except (BrokenPipeError, OSError):
            pass

    threading.Thread(target=forward_input, daemon=True).start()
    threading.Thread(target=forward_output, daemon=True).start()
    threading.Thread(target=forward_stderr, daemon=True).start()
    while not input_closed.wait(.01):
        if child.poll() is not None:
            output_closed.wait(.1)
            return child.returncode
    # No kill/wait: only the disposable proxy remains, with stdin already closed.
    # Its normal two-second pipe drain disconnects the backend, which keeps its TTL.
    trace("exiting after EOF")
    # Interpreter shutdown can close pipe objects while a reader is blocked in
    # ReadFile, waiting for the proxy's drain. Exit without that finalization.
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["bsl", "atlassian"])
    parser.add_argument("--lexical-only", action="store_true")
    argv = sys.argv[1:]
    separator = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:separator])
    arguments = argv[separator + 1:]
    runtime = json.loads((REPOSITORY / "mcp/runtime.json").read_text(encoding="utf-8"))
    command, env = command_for(args.kind, arguments, runtime, lexical_only=args.lexical_only)
    broker = "--mode" in arguments and arguments[arguments.index("--mode") + 1:][:1] == ["broker"]
    if os.name == "nt" and args.kind == "bsl" and broker:
        return run_windows_broker(command, env)
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print("MCP startup failed: " + type(error).__name__, file=sys.stderr)
        sys.exit(1)
