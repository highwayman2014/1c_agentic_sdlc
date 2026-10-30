import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from configure_mcp import build_profiles, discover_source, dump_servers, import_atlassian_auth, merge_json_servers, merge_servers, pi_native, standalone, write_backup
from mcp_profile import command_for, read_env
import configure_mcp


class McpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.worktree = self.root / "task"
        self.runtime = {
            "node": "node.exe", "wiki_entrypoint": "wiki.js", "openviking_url": "http://127.0.0.1:1933/mcp",
            "launcher": "shared-launcher.exe", "platform_help": str(self.root / "help"),
            "embedding_defaults": {"EMBEDDING_URL": "https://embedding.invalid/api", "EMBEDDING_MODEL": "test", "EMBEDDING_DIM": "1024"},
            "embedding_file": str(self.root / "embedding.env"), "atlassian_file": str(self.root / "atlassian.env"),
        }
        self.project = {"analyzers": [{"name": "bsl-test", "cache": str(self.root / "main-cache"),
                         "args": ["mcp", "serve", "--profile", "workspace", "--mode", "broker",
                                  "--source-dir", str(self.source), "--enable-tool", "references",
                                  "--cache-dir", str(self.root / "main-cache")]}]}

    def profiles(self, workspace=None, **kwargs):
        return build_profiles(self.project, workspace or self.worktree, self.source, self.runtime,
                              repository=self.root / "settings", personal_root=self.root / "home", **kwargs)

    def test_worktree_uses_own_sources_cache_and_shared_wiki(self):
        shared, local = self.profiles()
        analyzer = local["bsl-test-task"]
        args = analyzer["args"]
        self.assertEqual(args[args.index("--source-dir") + 1], str(self.worktree))
        self.assertNotEqual(args[args.index("--cache-dir") + 1], self.project["analyzers"][0]["cache"])
        self.assertEqual(local["llm-wiki-project"]["env"]["WIKI_ROOT"], str(self.source))
        self.assertFalse(local["rlm-tools-bsl"]["enabled"])
        self.assertIn("atlassian-mcp-server", shared)
        self.assertNotIn("smm-auto-prod-toolkit", standalone(shared, local)["mcpServers"])

    def test_preserves_worktree_cache_but_never_reuses_main_cache(self):
        old = {"bsl-existing": {"args": ["--cache-dir", str(self.root / "existing-cache")]}}
        _, local = self.profiles(existing_entries=old)
        self.assertIn(str(self.root / "existing-cache"), local["bsl-existing"]["args"])
        old["bsl-existing"]["args"][1] = self.project["analyzers"][0]["cache"]
        _, local = self.profiles(existing_entries=old)
        self.assertNotEqual(local["bsl-existing"]["args"][-1], self.project["analyzers"][0]["cache"])

    def test_toml_merge_preserves_unrelated_settings_and_multiline_text(self):
        text = '''model = "unchanged"
[mcp_servers.other]
command = "other.exe"
instructions = """
[mcp_servers.target]
This is text, not a table.
"""
[mcp_servers.target]
command = "old.exe"
disabled_tools = ["write"]
[mcp_servers.target.env]
OLD = "private"
[projects."source"]
trust_level = "trusted"
'''
        merged = merge_servers(text, {"target": {"command": "new.exe", "args": [], "env": {}}})
        data = tomllib.loads(merged)
        self.assertEqual(data["model"], "unchanged")
        self.assertIn("[mcp_servers.target]", data["mcp_servers"]["other"]["instructions"])
        self.assertEqual(data["mcp_servers"]["target"]["disabled_tools"], ["write"])
        self.assertEqual(data["mcp_servers"]["target"]["env"], {})
        self.assertEqual(data["projects"]["source"]["trust_level"], "trusted")

    def test_atlassian_auth_leaves_arguments_and_roundtrips_private_file(self):
        private_value = "test-fixture-token-$()-with=equals"
        old = dump_servers({"atlassian-mcp-server": {"command": "uvx", "args": [
            "mcp-atlassian", "--jira-url", "https://jira.invalid", "--jira-personal-token", private_value]}})
        import_atlassian_auth(old, self.runtime)
        self.assertEqual(read_env(self.runtime["atlassian_file"])["JIRA_PERSONAL_TOKEN"], private_value)
        shared, _ = self.profiles()
        public_config = merge_servers(old, {"atlassian-mcp-server": shared["atlassian-mcp-server"]})
        self.assertNotIn(private_value, public_config)
        self.assertNotIn("--jira-personal-token", public_config)

    def test_bsl_uses_shared_launcher_and_keeps_key_out_of_arguments(self):
        Path(self.runtime["embedding_file"]).write_text('EMBEDDING_API_KEY="test-fixture-value"\n', encoding="utf-8")
        command, env = command_for("bsl", ["mcp", "serve"], self.runtime,
                                   inherited={"EMBEDDING_URL": "https://unrelated.invalid"})
        self.assertEqual(command[0], "shared-launcher.exe")
        self.assertEqual(env["EMBEDDING_API_KEY"], "test-fixture-value")
        self.assertEqual(env["EMBEDDING_URL"], self.runtime["embedding_defaults"]["EMBEDDING_URL"])
        self.assertNotIn("test-fixture-value", command)
        _, lexical_env = command_for("bsl", [], self.runtime, inherited={}, lexical_only=True)
        self.assertFalse(any(key.startswith("EMBEDDING_") for key in lexical_env))

    def test_backups_stay_outside_project(self):
        project = self.root / "project"
        project.mkdir()
        target = project / ".mcp.json"
        target.write_text("old credential-bearing config", encoding="utf-8")
        backups = self.root / "private-backups"
        write_backup(target, "new config", backup_root=backups)
        saved = list(backups.rglob(".mcp.json"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_text(), "old credential-bearing config")
        self.assertEqual(list(project.iterdir()), [target])

    def test_claude_and_pi_keep_same_worktree_and_wiki_with_client_specific_fields(self):
        shared, local = self.profiles()
        claude = standalone(shared, local)["mcpServers"]
        pi = pi_native(shared, local)["mcpServers"]
        self.assertEqual(set(claude), set(pi) - {"rlm-tools-bsl"})
        self.assertEqual(claude["openviking"]["type"], "http")
        self.assertEqual(claude["bsl-test-task"]["type"], "stdio")
        self.assertEqual(claude["bsl-test-task"]["args"], pi["bsl-test-task"]["args"])
        self.assertNotIn("cwd", claude["bsl-test-task"])
        self.assertNotIn("type", pi["openviking"])
        self.assertEqual(pi["bsl-test-task"]["exposure"], "codemode")
        self.assertEqual(pi["bsl-test-task"]["timeout"], 120)
        self.assertEqual(pi["llm-wiki-project"]["env"]["WIKI_ROOT"], str(self.source))
        self.assertFalse(pi["rlm-tools-bsl"]["enabled"])
        self.assertNotIn("lifecycle", pi["bsl-test-task"])
        self.assertNotIn("requestTimeoutMs", pi["bsl-test-task"])

    def test_json_merge_preserves_preferences_and_refuses_unknown_analyzer_scopes(self):
        old = json.dumps({"settings": {"directTools": False}, "mcpServers": {
            "other": {"command": "unrelated"},
            "target": {"url": "https://old.invalid", "headers": {"Authorization": "old"}, "directTools": ["read"]},
            "bsl-original": {"args": ["workspace", "--source-dir", "source"]}}})
        entries = {"target": {"command": "new", "args": [], "env": {}}}
        with self.assertRaises(ValueError):
            merge_json_servers(old, entries)
        result = merge_json_servers(old, entries, {"bsl-original"})
        data = json.loads(result)
        self.assertEqual(data["settings"], {"directTools": False})
        self.assertEqual(data["mcpServers"]["other"], {"command": "unrelated"})
        self.assertEqual(data["mcpServers"]["target"]["directTools"], ["read"])
        self.assertNotIn("headers", data["mcpServers"]["target"])
        self.assertNotIn("bsl-original", data["mcpServers"])
        self.assertEqual(result, merge_json_servers(result, entries))

    def test_pi_and_claude_apply_without_codex_config(self):
        self.source.mkdir()
        subprocess.run(["git", "init", str(self.source)], check=True, capture_output=True)
        (self.source / "src/cf").mkdir(parents=True)
        (self.source / "src/cf/Configuration.xml").touch()
        (self.source / "bsl-analyzer.toml").write_text('[source]\nroot="src/cf"\n', encoding="utf-8")
        for key in ["launcher", "node", "wiki_entrypoint"]:
            component = self.root / (key + ".fixture")
            component.touch()
            self.runtime[key] = str(component)
        (self.root / "scripts").mkdir()
        (self.root / "scripts/mcp_profile.py").touch()
        (self.root / "mcp").mkdir()
        (self.root / "mcp/runtime.json").write_text(json.dumps(self.runtime), encoding="utf-8")
        (self.root / "mcp/projects.json").write_text(json.dumps({"smm_auto": {
            **self.project, "source": str(self.source)}}), encoding="utf-8")
        for client, target in [("pi", ".pi/mcp.json"), ("claude", ".mcp.json")]:
            with patch.object(configure_mcp, "REPOSITORY", self.root), patch("builtins.print"), patch.object(sys, "argv", [
                "configure_mcp.py", "--workspace", str(self.source), "--client", client, "--apply"]):
                configure_mcp.main()
            data = json.loads((self.source / target).read_text(encoding="utf-8"))
            self.assertEqual(len(data["mcpServers"]), 6)
            self.assertFalse((self.source / ".codex").exists())
            if client == "pi":
                self.assertFalse((self.source / ".mcp.json").exists())

    def test_real_git_worktree_source_and_manifest_mismatch(self):
        self.source.mkdir()
        def run(*args):
            subprocess.run(["git", *args], check=True, capture_output=True)
        run("init", str(self.source))
        (self.source / "file.txt").write_text("fixture", encoding="utf-8")
        run("-C", str(self.source), "add", "file.txt")
        run("-C", str(self.source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-m", "fixture")
        run("-C", str(self.source), "worktree", "add", "-b", "task", str(self.worktree))
        self.assertEqual(discover_source(self.worktree), self.source.resolve())
        (self.worktree / ".worktree-task.json").write_text(json.dumps({"source": str(self.root / "wrong")}), encoding="utf-8")
        with self.assertRaises(ValueError):
            discover_source(self.worktree)


if __name__ == "__main__":
    unittest.main()
