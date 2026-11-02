import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from unified_bsl import configure, workspace_from_environment
from configure_mcp import build_profiles
from install_unified_bsl import install
import json
import tomllib


class UnifiedTests(unittest.TestCase):
    def test_source_discovery_stops_at_git_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bsl-analyzer.toml").write_text("")
            project = root / "project"
            project.mkdir()
            (project / ".git").write_text("gitdir: elsewhere")
            self.assertIsNone(workspace_from_environment({"CLAUDE_PROJECT_DIR": str(project)}))
            (project / "bsl-analyzer.toml").write_text("")
            self.assertEqual(workspace_from_environment({"CLAUDE_PROJECT_DIR": str(project)}), project.resolve())

    def test_workspace_keeps_live_connections_and_removes_provider_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bsl-analyzer.toml").write_text("[source]\nroot='src/cf'\n")
            runtime = {"unified_cache": str(root / "cache"), "platform_help": str(root)}
            cmd = ["app", "mcp", "serve", "--profile", "workspace", "--mode", "stdio",
                   "--source-dir", "empty", "--cache-dir", "live-cache"]
            def live(settings, env):
                self.assertNotIn("EMBEDDING_API_KEY", env)
                self.assertNotIn("BSL_MCP_EFFECTIVE_EMBEDDING_URL", env)
                return list(cmd), {**env, "BSL_ONEC_CONNECTIONS_FILE": "connections.json"}
            with patch("onec_runtime.configure", side_effect=live), patch("mcp_profile.enforce_baseline_launch_policy") as gate:
                command, env = configure(runtime, {"CLAUDE_PROJECT_DIR": str(root),
                    "EMBEDDING_API_KEY": "private", "BSL_MCP_EFFECTIVE_EMBEDDING_URL": "provider"}, root)
            self.assertEqual(command[command.index("--source-dir") + 1], str(root.resolve()))
            self.assertEqual(command[command.index("--mode") + 1], "broker")
            self.assertEqual(env["BSL_ONEC_CONNECTIONS_FILE"], "connections.json")
            gate.assert_called_once()

    def test_paused_source_is_rejected_before_credentials_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bsl-analyzer.toml").write_text("")
            with patch("mcp_profile.enforce_baseline_launch_policy", side_effect=ValueError("paused")), patch("onec_runtime.configure") as live:
                with self.assertRaisesRegex(ValueError, "paused"):
                    configure({}, {"CLAUDE_PROJECT_DIR": str(root)}, root)
                live.assert_not_called()

    def test_unified_profile_replaces_reference_workspace_and_live(self):
        project = {"unified": True, "live_server": "bsl-smm-live", "analyzers": [{
            "name": "bsl-smm", "cache": "cache", "args": ["--source-dir", "source", "--cache-dir", "cache"]}]}
        runtime = {"node": "node", "wiki_entrypoint": "wiki", "openviking_url": "http://localhost"}
        shared, local = build_profiles(project, Path.cwd(), Path.cwd(), runtime)
        self.assertEqual([n for n in shared if n.startswith("bsl")], ["bsl"])
        self.assertEqual([n for n in local if n.startswith("bsl")], ["bsl"])
        self.assertIn("bsl-unified", local["bsl"]["args"])

    def test_new_project_only_requires_a_source_in_registry(self):
        runtime = {"node": "node", "wiki_entrypoint": "wiki", "openviking_url": "http://localhost"}
        shared, local = build_profiles({"source": str(Path.cwd())}, Path.cwd(), Path.cwd(), runtime)
        self.assertIn("bsl", shared)
        self.assertIn("bsl", local)
        self.assertEqual(local["bsl"]["cwd"], str(Path.cwd()))

    def test_install_preserves_other_servers_and_client_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".codex").mkdir()
            (home / ".codex/config.toml").write_text('model="keep"\n[mcp_servers.bsl-reference]\ncommand="old"\n[mcp_servers.other]\ncommand="keep"\n')
            (home / ".claude.json").write_text(json.dumps({"projects": {"source": {"trusted": True}}, "mcpServers": {"other": {"url": "http://keep"}}}))
            install(home, apply=True)
            codex = tomllib.loads((home / ".codex/config.toml").read_text())
            self.assertEqual(codex["model"], "keep")
            self.assertEqual(set(codex["mcp_servers"]), {"bsl", "other"})
            claude = json.loads((home / ".claude.json").read_text())
            self.assertTrue(claude["projects"]["source"]["trusted"])
            self.assertEqual(claude["mcpServers"]["other"]["url"], "http://keep")


if __name__ == "__main__":
    unittest.main()
