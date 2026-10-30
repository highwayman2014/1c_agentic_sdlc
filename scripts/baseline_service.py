"""Check or provision the local PostgreSQL baseline service; never invoke an embedder."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time

IMAGE = "pgvector/pgvector@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d"
CONTAINER = "bsl-baseline-postgres"
VOLUME = "bsl-baseline-pg17"
PRIVATE = Path("D:/tools/bsl-baseline")


def docker(*args, input=None):
    result = subprocess.run(["docker", *args], input=input, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("Local baseline Docker operation failed; private output withheld")
    return result.stdout


def inspect():
    result = subprocess.run(["docker", "container", "inspect", CONTAINER], text=True, capture_output=True)
    if result.returncode:
        return None
    data = json.loads(result.stdout)[0]
    if data["Config"]["Image"] != IMAGE:
        raise RuntimeError("Existing container uses a different image")
    bindings = data["HostConfig"]["PortBindings"].get("5432/tcp", [])
    if bindings != [{"HostIp": "127.0.0.1", "HostPort": "15432"}]:
        raise RuntimeError("Existing container uses different port bindings")
    if not any(m.get("Name") == VOLUME and m["Destination"] == "/var/lib/postgresql/data" for m in data["Mounts"]):
        raise RuntimeError("Existing container uses a different data volume")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    existing = inspect()
    if not args.apply:
        print(json.dumps({"container": CONTAINER, "exists": existing is not None,
                          "running": bool(existing and existing["State"]["Running"]),
                          "address": "127.0.0.1:15432", "volume": VOLUME}))
        return
    PRIVATE.mkdir(parents=True, exist_ok=True)
    env = PRIVATE / "postgres.env"
    reader = PRIVATE / "reader.json"
    volume_exists = subprocess.run(["docker", "volume", "inspect", VOLUME], capture_output=True).returncode == 0
    if (existing or volume_exists) and (not env.exists() or not reader.exists()):
        raise RuntimeError("Existing service credentials are missing; refusing to replace them")
    if not env.exists():
        env.write_text("POSTGRES_USER=bsl_admin\nPOSTGRES_DB=bsl_baseline\nPOSTGRES_PASSWORD=" + secrets.token_hex(24) + "\n", encoding="utf-8")
    if not reader.exists():
        reader.write_text(json.dumps({"user": "bsl_reader", "password": secrets.token_hex(24)}), encoding="utf-8")
    if existing is None:
        docker("pull", IMAGE)
        docker("run", "-d", "--name", CONTAINER, "--restart", "unless-stopped", "--env-file", str(env),
               "-p", "127.0.0.1:15432:5432", "-v", VOLUME + ":/var/lib/postgresql/data", IMAGE)
    elif not existing["State"]["Running"]:
        docker("start", CONTAINER)
    for attempt in range(30):
        ready = subprocess.run(["docker", "exec", CONTAINER, "pg_isready", "-U", "bsl_admin", "-d", "bsl_baseline"], capture_output=True)
        if ready.returncode == 0:
            break
        if attempt == 29:
            raise RuntimeError("Local PostgreSQL did not become ready within 30 seconds")
        time.sleep(1)
    password = json.loads(reader.read_text(encoding="utf-8"))["password"].replace("'", "''")
    sql = ("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='bsl_reader') THEN "
           "CREATE ROLE bsl_reader LOGIN PASSWORD '" + password + "'; END IF; END $role$;\n"
           "GRANT CONNECT ON DATABASE bsl_baseline TO bsl_reader;\n"
           "ALTER ROLE bsl_reader SET default_transaction_read_only=on;\n"
           "DO $grant$ BEGIN IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='smm_auto') THEN "
           "GRANT USAGE ON SCHEMA smm_auto TO bsl_reader; "
           "GRANT SELECT ON ALL TABLES IN SCHEMA smm_auto TO bsl_reader; "
           "ALTER DEFAULT PRIVILEGES FOR ROLE bsl_admin IN SCHEMA smm_auto GRANT SELECT ON TABLES TO bsl_reader; "
           "END IF; END $grant$;\n")
    docker("exec", "-i", CONTAINER, "psql", "-U", "bsl_admin", "-d", "bsl_baseline", "-v", "ON_ERROR_STOP=1", input=sql)
    print("Local baseline service ready; source indexes and embedding provider were not used")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else "Baseline setup failed; private output withheld", file=sys.stderr)
        sys.exit(1)
