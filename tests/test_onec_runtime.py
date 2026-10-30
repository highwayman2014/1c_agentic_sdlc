import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from onec_runtime import configure
from configure_mcp import build_profiles, pi_native
from mcp_profile import command_for


class OnecRuntimeTests(unittest.TestCase):
    def test_credentials_are_selected_by_id_and_ref_and_embeddings_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "connections.json"
            registry.write_text(json.dumps({"connections": {"dev": {"url": "http://fixture/hs/bsl-analyzer",
                "user_env": "DEV_USER", "password_env": "DEV_PASSWORD", "allow_execute": False}}}))
            database = root / ".v8-project.json"
            database.write_text(json.dumps({"databases": [{"id": "dev", "ref": "fixture_dev", "user": "reader", "password": "fixture-secret"}]}))
            sources = root / "sources.json"
            sources.write_text(json.dumps({"dev": {"file": str(database), "database_id": "dev", "expected_ref": "fixture_dev"}}))
            runtime = {"onec_connections": str(registry), "onec_credential_sources": str(sources),
                       "live_source": str(root / "empty"), "live_cache": str(root / "cache"), "broker_application": "shared-app.exe"}
            command, env = configure(runtime, {"EMBEDDING_API_KEY": "fixture-key", "EMBEDDING_URL": "http://paid", "BSL_SEARCH_BASELINE_PG_URL": "fixture", "BSL_ONEC_PASSWORD": "old", "PATH": "fixture-path"})
            self.assertEqual(env["DEV_PASSWORD"], "fixture-secret")
            self.assertEqual(env["PATH"], "fixture-path")
            self.assertFalse(any(k.startswith(("EMBEDDING_", "BSL_SEARCH_")) for k in env))
            self.assertNotIn("BSL_ONEC_PASSWORD", env)
            self.assertNotIn("fixture-secret", " ".join(command))
            self.assertEqual(command[0], "shared-app.exe")
            self.assertIn("stdio", command)
            self.assertEqual(list((root / "empty").iterdir()), [])
            (root / "empty" / "source.bsl").write_text("fixture")
            with self.assertRaisesRegex(ValueError, "must remain empty"):
                configure(runtime, {})
            (root / "empty" / "source.bsl").unlink()
            sources.write_text(json.dumps({"dev": {"file": str(database), "database_id": "dev", "expected_ref": "production"}}))
            with self.assertRaisesRegex(ValueError, "exactly one dev"):
                configure(runtime, {})

    def test_runtime_does_not_accept_source_or_embedding_arguments(self):
        with self.assertRaisesRegex(ValueError, "fixed source"):
            command_for("bsl-live", ["--source-dir", "real-project"], {}, inherited={})

    def test_pi_exposes_only_http_tools(self):
        entry = {"command": "python", "args": ["runner.py", "bsl-live"]}
        result = pi_native({}, {"bsl-smm-live": entry})["mcpServers"]["bsl-smm-live"]
        self.assertEqual(result["toolExposure"]["*"], "hidden")
        self.assertEqual({k for k, v in result["toolExposure"].items() if v == "codemode"}, {"metadata", "query", "execute", "event_log"})


if __name__ == "__main__":
    unittest.main()
