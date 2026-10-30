"""Move local adapter connections to native pi MCP; never print credentials."""
import argparse
import json
from pathlib import Path
import sys

from configure_mcp import REPOSITORY, write_backup


def convert_server(entry):
    supported = {"command", "args", "env", "cwd", "url", "headers", "description", "oauth", "auth", "type"}
    adapter_fields = {"disabled", "lifecycle", "idleTimeout", "requestTimeoutMs", "directTools", "includeTools", "excludeTools"}
    native_fields = {"timeout", "enabled", "exposure", "toolExposure"}
    if set(entry) - supported - adapter_fields - native_fields:
        raise ValueError("Server contains unsupported adapter fields; review before migration")
    if entry.get("auth") or entry.get("oauth"):
        raise ValueError("OAuth/provider authentication needs a separate native sign-in; migration stopped")
    native = {key: value for key, value in entry.items() if key in supported | native_fields}
    native.setdefault("timeout", entry.get("requestTimeoutMs", 120000) / 1000)
    if "disabled" in entry:
        native["enabled"] = not entry["disabled"]
    direct = entry.get("directTools", False)
    if direct == "search":
        native.setdefault("exposure", "deferred")
    else:
        native.setdefault("exposure", "direct" if direct is True else "codemode")
    rules = dict(native.get("toolExposure", {}))
    if isinstance(direct, list):
        rules.update({name: "direct" for name in direct})
    include, exclude = entry.get("includeTools"), entry.get("excludeTools", [])
    if include is not None or exclude:
        # Exact tool names can be translated without changing precedence.
        # Pattern intersections require manual review rather than opening more tools.
        if any("*" in name for name in [*(include or []), *exclude]):
            raise ValueError("Review wildcard tool filters before migration")
        if include is not None:
            rules = {name: value for name, value in rules.items() if name in include}
            rules.update({name: rules.get(name, native["exposure"]) for name in include})
            rules["*"] = "hidden"
        rules.update({name: "hidden" for name in exclude})
    if rules:
        native["toolExposure"] = rules
    return native


def without_adapter(settings):
    updated = dict(settings)
    packages = settings.get("packages", [])
    def adapter(value):
        source = value.get("source", "") if isinstance(value, dict) else value
        return isinstance(source, str) and (source == "npm:pi-mcp-adapter" or source.startswith("npm:pi-mcp-adapter@"))
    updated["packages"] = [value for value in packages if not adapter(value)]
    extensions = [value for value in settings.get("extensions", [])
                  if value != "-builtin:mcp" and "pi-mcp-adapter" not in value]
    if "builtin:mcp" not in extensions:
        extensions.append("builtin:mcp")
    updated["extensions"] = extensions
    return updated


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def migrate(home, apply=False, defaults=None):
    home = Path(home)
    agent = home / ".pi/agent"
    # Same precedence as the adapter's normal user-level sources.
    sources = [home / ".config/mcp/mcp.json", home / ".agents/mcp.json",
               home / ".agents/mcp/mcp.json", agent / "mcp-adapter.json"]
    target = agent / "mcp.json"
    current = read_json(target)
    combined = {}
    for path in sources:
        data = read_json(path)
        if set(data) - {"mcpServers"}:
            raise ValueError("Adapter source has imports/settings requiring review: " + str(path))
        for name, entry in data.get("mcpServers", {}).items():
            combined[name] = {**combined.get(name, {}), **entry}
    existing = current.get("mcpServers", {})
    migrated = {name: convert_server(entry) for name, entry in combined.items() if name not in existing}
    result = {**current, "mcpServers": {**(defaults or {}), **migrated, **existing}}
    settings_path = agent / "settings.json"
    settings = without_adapter(read_json(settings_path))
    if apply:
        # Write the configuration before enabling the native extension.
        write_backup(target, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        write_backup(settings_path, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
    print("Native pi migration " + ("applied" if apply else "preview") + ": " + str(len(result["mcpServers"])) + " connections; existing native entries preserved.")
    print("Adapter files and installed package remain on disk. Restart pi to load native MCP.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    defaults = read_json(REPOSITORY / "mcp/configs/shared/pi/mcp.json").get("mcpServers", {})
    migrate(Path.home(), args.apply, defaults)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
