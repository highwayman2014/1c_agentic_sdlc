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

    def test_explicit_embedding_approval_loads_only_private_provider_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bsl-analyzer.toml').write_text('')
            runtime = {'embedding_defaults': {'EMBEDDING_MODEL': 'saved-model', 'EMBEDDING_BATCH_SIZE': '128'},
                       'unified_embedding_defaults': {'EMBEDDING_BATCH_SIZE': '8'},
                       'embedding_file': 'private.env', 'unified_cache': str(root / 'cache'),
                       'platform_help': 'absent'}
            cmd = ['app', '--source-dir', 'empty', '--mode', 'stdio', '--cache-dir', 'cache']
            with patch('mcp_profile.enforce_baseline_launch_policy', return_value='embeddings-enabled'), \
                 patch('mcp_profile.read_env', return_value={'EMBEDDING_API_KEY': 'fixture', 'OTHER_SECRET': 'discard'}) as read, \
                 patch('onec_runtime.configure', side_effect=lambda settings, env: (list(cmd), {k:v for k,v in env.items() if not k.startswith('EMBEDDING_')})):
                _, env = configure(runtime, {'CLAUDE_PROJECT_DIR': str(root),
                    'EMBEDDING_MODEL': 'untrusted', 'BSL_MCP_EFFECTIVE_EMBEDDING_MODEL': 'stale'}, root)
            self.assertEqual(env['EMBEDDING_API_KEY'], 'fixture')
            self.assertEqual(env['EMBEDDING_MODEL'], 'saved-model')
            self.assertEqual(env['EMBEDDING_CONCURRENCY'], '1')
            self.assertEqual(env['EMBEDDING_BATCH_SIZE'], '8')
            self.assertNotIn('OTHER_SECRET', env)
            self.assertNotIn('BSL_MCP_EFFECTIVE_EMBEDDING_MODEL', env)
            read.assert_called_once_with('private.env')

    def test_workspace_request_byte_budget_overrides_provider_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bsl-analyzer.toml').write_text('')
            runtime = {'embedding_defaults': {}, 'embedding_file': 'private.env',
                       'unified_cache': str(root / 'cache'), 'platform_help': 'absent',
                       'unified_workspace_embedding_max_request_bytes': {str(root): 65536}}
            cmd = ['app', '--source-dir', 'empty', '--mode', 'stdio', '--cache-dir', 'cache']
            with patch('mcp_profile.enforce_baseline_launch_policy', return_value='embeddings-enabled'), \
                 patch('mcp_profile.read_env', return_value={'EMBEDDING_API_KEY': 'fixture', 'EMBEDDING_MAX_REQUEST_BYTES': '1048576'}), \
                 patch('onec_runtime.configure', side_effect=lambda settings, env: (list(cmd), dict(env))):
                _, env = configure(runtime, {'CLAUDE_PROJECT_DIR': str(root)}, root)
            self.assertEqual(env['EMBEDDING_MAX_REQUEST_BYTES'], '65536')

    def test_invalid_request_byte_budget_stops_before_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bsl-analyzer.toml').write_text('')
            for value in [0, -1, True, '65536']:
                runtime = {'unified_workspace_embedding_max_request_bytes': {str(root): value}}
                with self.subTest(value=value), \
                     patch('mcp_profile.enforce_baseline_launch_policy', return_value='embeddings-enabled'), \
                     patch('mcp_profile.read_env') as read:
                    with self.assertRaisesRegex(ValueError, 'positive integer'):
                        configure(runtime, {'CLAUDE_PROJECT_DIR': str(root)}, root)
                    read.assert_not_called()

    def test_approved_source_without_credential_does_not_start_live_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bsl-analyzer.toml').write_text('')
            with patch('mcp_profile.enforce_baseline_launch_policy', return_value='embeddings-enabled'), \
                 patch('mcp_profile.read_env', return_value={}), patch('onec_runtime.configure') as live:
                with self.assertRaisesRegex(ValueError, 'no private provider credential'):
                    configure({'embedding_defaults': {}, 'embedding_file': 'missing'},
                              {'CLAUDE_PROJECT_DIR': str(root)}, root)
                live.assert_not_called()

    def test_explicit_lexical_only_disables_even_an_approved_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bsl-analyzer.toml').write_text('')
            runtime = {'unified_cache': str(root / 'cache'), 'platform_help': 'absent',
                       'unified_workspace_embedding_max_request_bytes': {str(root): 65536}}
            cmd = ['app', '--source-dir', 'empty', '--mode', 'stdio', '--cache-dir', 'cache']
            with patch('mcp_profile.enforce_baseline_launch_policy', return_value='embeddings-enabled'), \
                 patch('mcp_profile.read_env') as read, \
                 patch('onec_runtime.configure', side_effect=lambda settings, env: (list(cmd), dict(env))):
                _, env = configure(runtime, {'CLAUDE_PROJECT_DIR': str(root)}, root, lexical_only=True)
            read.assert_not_called()
            self.assertFalse(any(k.startswith('EMBEDDING_') for k in env))

    def test_paused_source_is_rejected_before_credentials_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bsl-analyzer.toml").write_text("")
            with patch("mcp_profile.enforce_baseline_launch_policy", side_effect=ValueError("paused")), patch("onec_runtime.configure") as live:
                with self.assertRaisesRegex(ValueError, "paused"):
                    configure({}, {"CLAUDE_PROJECT_DIR": str(root)}, root)
                live.assert_not_called()

    def test_incompatible_shared_snapshot_stops_before_provider_key_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'bsl-analyzer.toml').write_text('[search.baseline]\nbackend="postgres"\n')
            with patch('mcp_profile.enforce_baseline_launch_policy',return_value='embeddings-enabled'), \
                 patch('mcp_profile.validate_embedding_snapshot',side_effect=ValueError('incompatible snapshot')), \
                 patch('mcp_profile.read_env') as read, patch('onec_runtime.configure') as live:
                with self.assertRaisesRegex(ValueError,'incompatible snapshot'):
                    configure({}, {'CLAUDE_PROJECT_DIR':str(root)},root)
                read.assert_not_called();live.assert_not_called()

    def test_low_memory_stops_before_credentials_and_live_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'bsl-analyzer.toml').write_text('')
            runtime={'unified_workspace_min_available_mib':{str(root):4096}}
            with patch('mcp_profile.enforce_baseline_launch_policy',return_value='embeddings-enabled'), \
                 patch('unified_bsl.available_memory_mib',return_value=512), \
                 patch('mcp_profile.read_env') as read, patch('onec_runtime.configure') as live:
                with self.assertRaisesRegex(ValueError,'memory budget'):
                    configure(runtime,{'CLAUDE_PROJECT_DIR':str(root)},root)
                read.assert_not_called();live.assert_not_called()

    def test_cache_override_is_exact_source_not_inherited_by_child(self):
        from unified_bsl import workspace_setting
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();runtime={'unified_workspace_caches':{str(root):'isolated'}}
            self.assertEqual(workspace_setting(runtime,'unified_workspace_caches',root,'default'),'isolated')
            self.assertEqual(workspace_setting(runtime,'unified_workspace_caches',root/'child','default'),'default')

    def test_workspace_application_is_exact_and_does_not_replace_global_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            other = root / 'other'
            other.mkdir()
            for folder in (root, other):
                (folder / 'bsl-analyzer.toml').write_text('')
            app = root / 'private-app'
            app.write_bytes(b'fixture')
            pointer = root / 'current'
            global_app = root / 'bsl-analyzer-original'
            global_app.write_bytes(b'fixture')
            pointer.write_text(global_app.name)
            runtime = {'unified_workspace_applications': {str(root): str(app)},
                       'broker_current': str(pointer), 'unified_cache': 'cache', 'platform_help': 'absent'}
            def live(settings, env):
                return [settings['broker_application'], '--source-dir', 'empty', '--mode', 'stdio', '--cache-dir', 'cache'], env
            with patch('mcp_profile.enforce_baseline_launch_policy', return_value='lexical-only'), \
                 patch('onec_runtime.configure', side_effect=live):
                command, _ = configure(runtime, {'CLAUDE_PROJECT_DIR': str(root)}, root)
                other_command, _ = configure(runtime, {'CLAUDE_PROJECT_DIR': str(other)}, root)
            self.assertEqual(command[0], str(app))
            self.assertEqual(other_command[0], str(global_app))
            self.assertEqual(pointer.read_text(), global_app.name)
            self.assertNotIn('broker_application', runtime)

    def test_missing_workspace_application_stops_before_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'bsl-analyzer.toml').write_text('')
            runtime = {'unified_workspace_applications': {str(root): str(root / 'absent')}}
            with patch('mcp_profile.enforce_baseline_launch_policy', return_value='embeddings-enabled'), \
                 patch('mcp_profile.read_env') as read, patch('onec_runtime.configure') as live:
                with self.assertRaisesRegex(ValueError, 'existing local file'):
                    configure(runtime, {'CLAUDE_PROJECT_DIR': str(root)}, root)
                read.assert_not_called()
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
