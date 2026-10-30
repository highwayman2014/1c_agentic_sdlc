"""Render or apply ready Windows MCP profiles. No servers, indexes or databases are started."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

from mcp_profile import ATLASSIAN_KEYS, REPOSITORY, read_env


def git(workspace, *arguments):
    result = subprocess.run(["git", "-C", str(workspace), *arguments], capture_output=True,
                            text=True, encoding="utf-8")
    if result.returncode:
        raise ValueError("Cannot inspect Git worktree: " + str(workspace))
    return result.stdout.strip()


def discover_source(workspace):
    workspace = Path(workspace).resolve()
    common = Path(git(workspace, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    if common.name != ".git":
        raise ValueError("Cannot infer source checkout from this Git layout; use --source")
    source = common.parent.resolve()
    manifest = workspace / ".worktree-task.json"
    if manifest.exists():
        declared = Path(json.loads(manifest.read_text(encoding="utf-8-sig"))["source"]).resolve()
        if declared != source:
            raise ValueError("Worktree manifest and Git common directory disagree")
    return source


def server(command, args, cwd=None, env=None):
    value = {"command": str(command), "args": list(args),
             "startup_timeout_sec": 120, "tool_timeout_sec": 120}
    if cwd is not None:
        value["cwd"] = str(cwd)
    if env is not None:
        value["env"] = env
    return value


def worktree_server_name(analyzer, workspace):
    return analyzer.get("worktree_name", analyzer["name"] + "-" + workspace.name)


def build_profiles(project, workspace, source, runtime, repository=REPOSITORY,
                   personal_root=None, existing_entries=None):
    workspace, source = Path(workspace), Path(source)
    personal_root = Path.home() if personal_root is None else Path(personal_root)
    runner = str(Path(repository) / "scripts/mcp_profile.py")
    shared = {
        "bsl-reference": server(sys.executable, [runner, "bsl", "--", "mcp", "serve", "--profile", "reference"], env={}),
        "openviking": {"url": runtime["openviking_url"], "startup_timeout_sec": 120, "tool_timeout_sec": 120},
        "llm-wiki-personal": server(runtime["node"], [runtime["wiki_entrypoint"]], env={"WIKI_ROOT": str(personal_root)}),
        "atlassian-mcp-server": server(sys.executable, [runner, "atlassian"], env={}),
    }
    shared["bsl-reference"]["env_vars"] = ["NAPARNIK_TOKEN"]
    local = {}
    is_worktree = workspace.resolve() != source.resolve()
    for analyzer in project["analyzers"]:
        args = list(analyzer["args"])
        args[args.index("--source-dir") + 1] = str(workspace)
        if is_worktree:
            base = analyzer["name"][4:]
            cache = personal_root / "AppData/Local/bsl-analyzer-cache/worktrees" / (base + "-" + workspace.name)
        else:
            cache = Path(analyzer["cache"])
        args[args.index("--cache-dir") + 1] = str(cache)
        name = worktree_server_name(analyzer, workspace) if is_worktree else analyzer["name"]
        if existing_entries and len(project["analyzers"]) == 1 and len(existing_entries) == 1:
            previous_name, previous = next(iter(existing_entries.items()))
            if not analyzer.get("worktree_name"):
                name = previous_name
            previous_args = previous.get("args", [])
            if "--cache-dir" in previous_args:
                previous_cache = Path(previous_args[previous_args.index("--cache-dir") + 1])
                if previous_cache.resolve() != Path(analyzer["cache"]).resolve() or not is_worktree:
                    args[args.index("--cache-dir") + 1] = str(previous_cache)
        local[name] = server(sys.executable, [runner, "bsl", "--", *args], workspace,
                             {"BSL_MCP_IDLE_TTL_SECS": "43200", "BSL_MCP_DAEMON_LOG": "1", "BSL_LOG": "info"})
    local["llm-wiki-project"] = server(runtime["node"], [runtime["wiki_entrypoint"]], workspace,
                                       {"WIKI_ROOT": str(source)})
    if project.get("live_server"):
        local[project["live_server"]] = server(sys.executable, [runner, "bsl-live"], workspace)
    if is_worktree:
        local["rlm-tools-bsl"] = {"url": "http://127.0.0.1:9000/mcp", "enabled": False}
    return shared, local


def toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(key) + " = " + toml_value(item) for key, item in value.items()) + " }"
    raise ValueError("Unsupported TOML value type")


def dump_servers(entries):
    lines = []

    def table(prefix, data):
        lines.append("[" + prefix + "]")
        for key, value in data.items():
            if not isinstance(value, dict):
                lines.append(json.dumps(key) + " = " + toml_value(value))
        lines.append("")
        for key, value in data.items():
            if isinstance(value, dict):
                table(prefix + "." + json.dumps(key), value)

    for name, entry in entries.items():
        table("mcp_servers." + json.dumps(name), entry)
    return "\n".join(lines)


def advance_multiline(line, state):
    position = 0
    while position < len(line):
        if state:
            if line.startswith(state, position):
                position += 3
                state = None
            elif state == '"""' and line[position] == "\\":
                position += 2
            else:
                position += 1
        elif line[position] == "#":
            break
        elif line.startswith('"""', position) or line.startswith("'''", position):
            state = line[position:position + 3]
            position += 3
        elif line[position] in "\"'":
            quote = line[position]
            position += 1
            while position < len(line):
                if quote == '"' and line[position] == "\\":
                    position += 2
                elif line[position] == quote:
                    position += 1
                    break
                else:
                    position += 1
        else:
            position += 1
    return state


def merge_servers(text, entries, retire=()):
    before = tomllib.loads(text)
    old = before.get("mcp_servers", {})
    desired = {name: {**old.get(name, {}), **entry} for name, entry in entries.items()}
    for entry in desired.values():
        if "url" in entry:
            for key in ["command", "args", "cwd", "env", "env_vars"]:
                entry.pop(key, None)
        else:
            for key in ["url", "bearer_token_env_var", "http_headers", "env_http_headers"]:
                entry.pop(key, None)
    managed = set(entries) | set(retire)
    keep, state, skip = [], None, False
    for line in text.splitlines(keepends=True):
        if state is None and re.match(r"^\s*\[.+\]\s*(?:#.*)?$", line.rstrip()):
            header = tomllib.loads(line)
            names = list(header.get("mcp_servers", {}))
            skip = bool(names and names[0] in managed)
        state = advance_multiline(line, state)
        if not skip:
            keep.append(line)
    result = "".join(keep).rstrip() + "\n\n" + dump_servers(desired)
    after = tomllib.loads(result)
    if {k: v for k, v in before.items() if k != "mcp_servers"} != {k: v for k, v in after.items() if k != "mcp_servers"}:
        raise ValueError("Merge would change unrelated Codex settings")
    for name, entry in old.items():
        if name not in managed:
            if after["mcp_servers"][name] != entry:
                raise ValueError("Merge would change an unrelated MCP server")
    return result


def standalone(shared, local):
    entries = {}
    for name, entry in {**shared, **local}.items():
        if entry.get("enabled") is False:
            continue
        # Claude Code requires the HTTP type. Its stdio schema does not expose cwd;
        # all source paths and entrypoints in these profiles are absolute.
        entries[name] = {"type": "http" if "url" in entry else "stdio",
                         **{key: value for key, value in entry.items() if key in {"command", "args", "env", "url"}}}
    return {"mcpServers": entries}


def pi_native(shared, local):
    entries = {}
    for name, entry in {**shared, **local}.items():
        entries[name] = {key: value for key, value in entry.items()
                         if key in {"command", "args", "env", "url", "cwd", "enabled"}}
        entries[name].update(timeout=120, exposure="codemode")
        if "bsl-live" in entry.get("args", []):
            entries[name]["description"] = "Live dev 1C HTTP tools only. Always set connection=smm-auto-avasilyev. No project code index."
            entries[name]["toolExposure"] = {tool: "codemode" for tool in ["metadata", "query", "execute", "event_log"]}
            entries[name]["toolExposure"]["*"] = "hidden"
        if name == "openviking":
            entries[name]["description"] = "Confluence search only: viking://resources/confluence-1c/. Import only explicitly selected pages."
            entries[name]["toolExposure"] = {tool: "codemode" for tool in
                ["health", "find", "search", "list", "tree", "glob", "grep", "read", "add_resource"]}
            entries[name]["toolExposure"]["*"] = "hidden"
            if local:
                # A project HTTP definition would replace global headers entirely.
                # Native pi permits exposure-only overrides that retain user auth.
                entries[name] = {key: entries[name][key] for key in ("exposure", "toolExposure")}
    return {"mcpServers": entries}


def merge_json_servers(text, entries, origin_names=()):
    data = json.loads(text) if text else {}
    servers = data.setdefault("mcpServers", {})
    for name, entry in list(servers.items()):
        if name.startswith("bsl-") and name != "bsl-reference" and "workspace" in entry.get("args", []) and name not in entries:
            if name not in origin_names:
                raise ValueError("Review unexpected JSON analyzer profile: " + name)
            del servers[name]
    for name, entry in entries.items():
        merged = {**servers.get(name, {}), **entry}
        if not any(key in entry for key in ("command", "url", "type")):
            servers[name] = {key: value for key, value in merged.items()
                             if key in {"enabled", "exposure", "toolExposure"}}
            continue
        obsolete = ("command", "args", "cwd", "env") if "url" in entry else ("url", "headers", "oauth", "auth")
        for key in obsolete:
            merged.pop(key, None)
        # Native pi infers transport from command/url.
        if "type" not in entry:
            merged.pop("type", None)
        if "cwd" not in entry:
            merged.pop("cwd", None)
        servers[name] = merged
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def existing_analyzers(workspace):
    path = Path(workspace) / ".mcp.json"
    if not path.exists():
        return []
    entries = json.loads(path.read_text(encoding="utf-8-sig")).get("mcpServers", {})
    return {name: entry for name, entry in entries.items()
            if name.startswith("bsl-") and "workspace" in entry.get("args", [])
            and "--source-dir" in entry["args"]
            and Path(entry["args"][entry["args"].index("--source-dir") + 1]).resolve() == Path(workspace).resolve()}


def write_backup(path, text, backup_root=None):
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8-sig") == text:
        return
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_root = Path.home() / ".config/1c-agentic-sdlc/backups" if backup_root is None else Path(backup_root)
        identity = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
        backup = backup_root / identity / stamp
        backup.mkdir(parents=True)
        shutil.copy2(path, backup / path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def import_atlassian_auth(global_text, runtime):
    old = tomllib.loads(global_text).get("mcp_servers", {}).get("atlassian-mcp-server", {})
    values = {key: value for key, value in old.get("env", {}).items() if key in ATLASSIAN_KEYS}
    arguments = old.get("args", [])
    mapping = {"--jira-url": "JIRA_URL", "--jira-personal-token": "JIRA_PERSONAL_TOKEN",
               "--confluence-url": "CONFLUENCE_URL", "--confluence-personal-token": "CONFLUENCE_PERSONAL_TOKEN"}
    for index, argument in enumerate(arguments[:-1]):
        if argument in mapping:
            values[mapping[argument]] = arguments[index + 1]
    path = Path(runtime["atlassian_file"])
    values.update(read_env(path))
    if not (values.get("JIRA_URL") or values.get("CONFLUENCE_URL")):
        raise ValueError("Atlassian URLs are missing in both existing config and private env file")
    for value in values.values():
        if "\n" in value or "\r" in value:
            raise ValueError("Unsupported multiline credential")
    write_backup(path, "".join(key + "=" + json.dumps(value, ensure_ascii=False) + "\n" for key, value in sorted(values.items())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", choices=["smm_auto", "carsh_auto", "zup", "bp"])
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--repository", type=Path, default=REPOSITORY)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--client", choices=["codex", "claude", "pi", "all"], default="codex",
                        help="Client to apply; --output always renders files for all three clients")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-shared", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    runtime = json.loads((REPOSITORY / "mcp/runtime.json").read_text(encoding="utf-8"))
    registry = json.loads((REPOSITORY / "mcp/projects.json").read_text(encoding="utf-8"))
    if args.apply and not args.workspace:
        parser.error("--apply requires --workspace")
    if args.apply_shared and args.client not in {"codex", "all"}:
        parser.error("--apply-shared manages Codex only; pi/Claude project files include all shared servers")
    if args.workspace:
        workspace = args.workspace.resolve()
        discovered = discover_source(workspace)
        source = args.source.resolve() if args.source else discovered
        if source != discovered:
            raise ValueError("Explicit source disagrees with Git common directory")
        project_id = args.project or next((key for key, value in registry.items() if Path(value["source"]).resolve() == source), None)
        if project_id is None:
            raise ValueError("Unknown source project; provide --project")
        project = registry[project_id]
        if Path(project["source"]).resolve() != source:
            raise ValueError("Source does not match selected project")
    elif args.project:
        project = registry[args.project]
        source = workspace = Path(project["source"])
    else:
        project = registry["smm_auto"]
        source = workspace = Path(project["source"])
    previous_analyzers = existing_analyzers(workspace)
    shared, local = build_profiles(project, workspace, source, runtime, args.repository,
                                    existing_entries=previous_analyzers)
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / ".codex").mkdir(exist_ok=True)
        (args.output / ".codex/config.toml").write_text(dump_servers(local), encoding="utf-8")
        (args.output / ".mcp.json").write_text(json.dumps(standalone(shared, local), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.output / ".pi").mkdir(exist_ok=True)
        (args.output / ".pi/mcp.json").write_text(json.dumps(pi_native(shared, local), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Rendered ready files:", args.output)
    if args.check or args.apply:
        for path in [runtime["launcher"], runtime.get("broker_application", runtime["launcher"]), runtime["node"], runtime["wiki_entrypoint"], str(args.repository / "scripts/mcp_profile.py")]:
            if not Path(path).is_file():
                raise ValueError("Missing installed component: " + path)
        for entry in local.values():
            arguments = entry.get("args", [])
            if "workspace" not in arguments:
                continue
            if "--configuration-root" in arguments:
                if not (workspace / arguments[arguments.index("--configuration-root") + 1] / "Configuration.xml").is_file():
                    raise ValueError("Configuration root is missing")
            else:
                config_path = workspace / "bsl-analyzer.toml"
                if not config_path.is_file():
                    raise ValueError("Copy the project bsl-analyzer.toml into this worktree first")
                layout = tomllib.loads(config_path.read_text(encoding="utf-8-sig")).get("source", {})
                if not (workspace / layout.get("root", "src/cf") / "Configuration.xml").is_file():
                    raise ValueError("TOML configuration root is missing")
                for extension in layout.get("extensions", []):
                    value = extension["path"] if isinstance(extension, dict) else extension
                    if not list(workspace.glob(value)):
                        raise ValueError("TOML extension is missing: " + value)
            for index, value in enumerate(arguments[:-1]):
                if value == "--extension" and not (workspace / arguments[index + 1].split("=", 1)[-1]).is_dir():
                    raise ValueError("Configured extension is missing: " + arguments[index + 1])
        print("Paths and source layout: OK. MCP/index readiness was not tested.")
    if args.apply_shared:
        path = Path.home() / ".codex/config.toml"
        old = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        import_atlassian_auth(old, runtime)
        write_backup(path, merge_servers(old, shared))
        print("Applied shared MCP profiles; credentials remain outside Git.")
    origin_names = {entry["name"] for entry in project["analyzers"]}
    if (len(project["analyzers"]) == 1 and len(previous_analyzers) == 1
            and project["analyzers"][0].get("worktree_name")):
        # Only an unambiguous analyzer already bound to this exact source directory
        # can be retired when the project's explicit naming convention changes.
        origin_names.update(previous_analyzers)
    pending = {}
    if args.apply and args.client in {"codex", "claude", "all"}:
        path = workspace / ".mcp.json"
        text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        pending[path] = merge_json_servers(text, standalone(shared, local)["mcpServers"], origin_names)
    if args.apply and args.client in {"pi", "all"}:
        path = workspace / ".pi/mcp.json"
        text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        pending[path] = merge_json_servers(text, pi_native(shared, local)["mcpServers"], origin_names)
    if args.apply and args.client in {"codex", "all"}:
        global_path = Path.home() / ".codex/config.toml"
        global_servers = tomllib.loads(global_path.read_text(encoding="utf-8-sig")).get("mcp_servers", {})
        if not set(shared).issubset(global_servers):
            raise ValueError("Run --apply-shared before applying project profiles")
        path = workspace / ".codex/config.toml"
        old = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        previous = tomllib.loads(old).get("mcp_servers", {})
        stale = [name for name, entry in previous.items() if name.startswith("bsl-") and name != "bsl-reference" and "workspace" in entry.get("args", []) and name not in local]
        unsafe = [name for name in stale if name not in origin_names]
        if unsafe:
            raise ValueError("Review existing analyzer scopes before replacing them: " + ", ".join(unsafe))
        pending[path] = merge_servers(old, local, retire=[*shared, *stale])
    if args.apply:
        for path, text in pending.items():
            write_backup(path, text)
        print("Applied local MCP profiles (" + args.client + "):", workspace)
    if not any([args.output, args.check, args.apply, args.apply_shared]):
        print(dump_servers(local))


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
