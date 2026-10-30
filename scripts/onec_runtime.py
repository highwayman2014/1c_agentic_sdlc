"""Build the official analyzer's HTTP-only client configuration without embedding settings."""
import json
from pathlib import Path


def configure(runtime, inherited):
    registry_file = Path(runtime["onec_connections"])
    registry = json.loads(registry_file.read_text(encoding="utf-8"))["connections"]
    sources = json.loads(Path(runtime["onec_credential_sources"]).read_text(encoding="utf-8"))
    env = {k: v for k, v in inherited.items()
           if not k.startswith(("EMBEDDING_", "BSL_SEARCH_", "BSL_ONEC_"))
           and k not in {"BSL_CACHE_DIR", "BSL_MCP_CACHE_SCOPE"}}
    for name, connection in registry.items():
        source = sources[name]
        data = json.loads(Path(source["file"]).read_text(encoding="utf-8-sig"))
        matches = [d for d in data["databases"] if d.get("id") == source["database_id"]
                   and d.get("ref") == source["expected_ref"]]
        if len(matches) != 1:
            raise ValueError("1C credential source does not identify exactly one dev database")
        database = matches[0]
        if not database.get("user"):
            raise ValueError("1C dev user is missing")
        env[connection["user_env"]] = database["user"]
        env[connection["password_env"]] = database.get("password", "")
    env["BSL_ONEC_CONNECTIONS_FILE"] = str(registry_file)
    # A fixed empty project avoids reading/indexing CF or extensions, including while the
    # real workspace is paused. The official workspace profile owns the live tool surface.
    source = Path(runtime["live_source"])
    source.mkdir(parents=True, exist_ok=True)
    if list(source.iterdir()):
        raise ValueError("Live-only source directory must remain empty")
    command = [runtime["broker_application"], "mcp", "serve", "--profile", "workspace",
               "--mode", "stdio", "--source-dir", str(source), "--cache-dir", runtime["live_cache"]]
    return command, env
