"""Supply the local baseline reader URL through the analyzer's helper protocol."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import quote

PROTOCOL = "bsl-analyzer.postgres-helper.v1"


def resolve(request, profile, credentials):
    if (request.get("protocol") != PROTOCOL or request.get("action") != "resolve-url"
            or request.get("mode") != "reader" or request.get("vault_role_base") != "smm-auto-local"):
        raise ValueError("Only the configured local reader role is supported")
    host, port, database = profile["host"], profile["port"], profile["database"]
    user = quote(credentials["user"], safe="")
    password = quote(credentials["password"], safe="")
    return {"protocol": PROTOCOL, "ok": True,
            "url": f"postgres://{user}:{password}@{host}:{port}/{database}",
            "renewable": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parent.parent
    profile = json.loads((repository / "mcp/baselines.json").read_text(encoding="utf-8"))[args.profile]
    credentials = json.loads(Path(profile["credentials_file"]).read_text(encoding="utf-8"))
    request = json.loads(sys.stdin.readline())
    print(json.dumps(resolve(request, profile, credentials)))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"protocol": PROTOCOL, "ok": False,
                          "error": {"code": "local_reader_denied", "message": "Local baseline reader could not be resolved", "retryable": False}}))
        sys.exit(1)
