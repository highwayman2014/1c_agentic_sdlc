"""Install the common BSL connection without changing unrelated client settings."""
import argparse
import json
from pathlib import Path
import sys
from configure_mcp import REPOSITORY, merge_json_servers, merge_servers, pi_native, server, standalone, write_backup


def install(home, apply=False):
    home = Path(home)
    entry = server(sys.executable, [str(REPOSITORY / "scripts/mcp_profile.py"), "bsl-unified"], env={})
    retired = {"bsl-reference", "bsl-smm-live", "bsl-smm"}
    paths = {
        home / ".codex/config.toml": lambda old: merge_servers(old, {"bsl": entry}, retire=retired),
        home / ".pi/agent/mcp.json": lambda old: merge_json_servers(old, pi_native({"bsl": entry}, {})["mcpServers"], retire=retired),
        home / ".claude.json": lambda old: merge_json_servers(old, standalone({"bsl": entry}, {})["mcpServers"], retire=retired),
    }
    pending = {path: merge(path.read_text(encoding="utf-8-sig") if path.exists() else "")
               for path, merge in paths.items()}
    if apply:
        for path, text in pending.items():
            write_backup(path, text)
    print("Unified BSL " + ("installed" if apply else "validated") + " for Codex, pi and Claude Code.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    install(Path.home(), args.apply)
