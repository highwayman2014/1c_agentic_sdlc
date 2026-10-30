"""Run shared MCP installations; read credentials only from local files/environment."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

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
        return [runtime["launcher"], *arguments], env
    for key, value in read_env(runtime["atlassian_file"]).items():
        if key in ATLASSIAN_KEYS:
            env[key] = value
    if not (env.get("JIRA_URL") or env.get("CONFLUENCE_URL")):
        raise ValueError("Atlassian credentials are not configured; run configure_mcp.py --apply-shared")
    uvx = shutil.which("uvx")
    if not uvx:
        raise ValueError("uvx is not installed")
    return [uvx, "mcp-atlassian", *arguments], env


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
