import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from baseline_credentials import PROTOCOL, resolve
from baseline_service import schema_grants
from mcp_profile import command_for, enforce_baseline_launch_policy, validate_embedding_snapshot


class BaselineTests(unittest.TestCase):
    def test_service_grants_only_configured_schemas_and_quotes_names(self):
        sql = schema_grants(['project_one', 'project"two'])
        self.assertIn('GRANT USAGE ON SCHEMA "project_one"', sql)
        self.assertIn('GRANT USAGE ON SCHEMA "project""two"', sql)
        self.assertNotIn('GRANT INSERT', sql)
        self.assertEqual(schema_grants([]), '')
        with self.assertRaises(RuntimeError):
            schema_grants(['invalid$grant$name'])

    def test_reader_protocol_and_url_encoding(self):
        request = {"protocol": PROTOCOL, "action": "resolve-url", "mode": "reader", "vault_role_base": "fixture-reader"}
        profile = {"host": "127.0.0.1", "port": 15432, "database": "bsl_baseline", "vault_role_base": "fixture-reader"}
        value = resolve(request, profile, {"user": "reader", "password": "fixture@/:"})
        self.assertEqual(value["url"], "postgres://reader:fixture%40%2F%3A@127.0.0.1:15432/bsl_baseline")
        for key, invalid in [("mode", "writer"), ("mode", "migrator"), ("vault_role_base", "other"), ("protocol", "other")]:
            with self.assertRaises(ValueError):
                resolve({**request, key: invalid}, profile, {})

    def test_paused_policy_covers_main_and_all_project_worktrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = {"fixture": {"source": str(root / "main"), "worktrees_root": str(root / "trees"),
                                  "workspace_launch": "paused", "pause_reason": "No paid fill"}}
            for folder in (root / "main", root / "trees" / "task-1", root / "trees" / "task-2"):
                args = ["mcp", "serve", "--profile", "workspace", "--source-dir", str(folder)]
                with self.assertRaisesRegex(ValueError, "No paid fill"):
                    enforce_baseline_launch_policy(args, policy)
            enforce_baseline_launch_policy(["--profile", "reference"], policy)
            enforce_baseline_launch_policy(["--profile", "workspace", "--source-dir", str(root / "trees-neighbor")], policy)

    def test_exact_source_lexical_override_keeps_other_workspaces_paused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "trees" / "task-1"
            policy = {"fixture": {"source": str(root / "main"), "worktrees_root": str(root / "trees"),
                                  "workspace_launch": "paused", "pause_reason": "No paid fill",
                                  "lexical_only_sources": [str(task)]}}
            args = ["--profile", "workspace", "--source-dir", str(task)]
            self.assertEqual(enforce_baseline_launch_policy(args, policy), "lexical-only")
            for other in (root / "main", task / "child", root / "trees" / "task-2"):
                with self.assertRaisesRegex(ValueError, "No paid fill"):
                    enforce_baseline_launch_policy([*args[:-1], str(other)], policy)

    def test_embedding_approval_is_exact_and_conflicting_modes_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / 'main'
            policy = {'fixture': {'source': str(main), 'worktrees_root': str(root / 'trees'),
                'workspace_launch': 'paused', 'pause_reason': 'not approved',
                'embedding_sources': [str(main)]}}
            args = ['--profile', 'workspace', '--source-dir', str(main)]
            self.assertEqual(enforce_baseline_launch_policy(args, policy), 'embeddings-enabled')
            with self.assertRaisesRegex(ValueError, 'not approved'):
                enforce_baseline_launch_policy([*args[:-1], str(root / 'trees' / 'task')], policy)
            policy['fixture']['lexical_only_sources'] = [str(main)]
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                enforce_baseline_launch_policy(args, policy)

    def test_lexical_policy_removes_inherited_embedding_settings_without_reading_keys(self):
        inherited = {"EMBEDDING_URL": "https://provider.invalid", "EMBEDDING_API_KEY": "fixture",
                     "BSL_MCP_EFFECTIVE_EMBEDDING_QUERY_PREFIX": "frozen", "KEEP": "yes"}
        runtime = {"launcher": "shared.exe", "platform_help": "missing-help"}
        with patch("mcp_profile.enforce_baseline_launch_policy", return_value="lexical-only"), patch("mcp_profile.read_env") as read:
            command, env = command_for("bsl", ["--profile", "workspace"], runtime, inherited=inherited)
            self.assertEqual(env, {"KEEP": "yes"})
            self.assertEqual(command[0], "shared.exe")
            read.assert_not_called()

    def test_unified_cli_preserves_explicit_lexical_guard(self):
        with patch('unified_bsl.configure', return_value=(['app'], {})) as configure:
            command_for('bsl-unified', [], {}, inherited={}, lexical_only=True)
            self.assertTrue(configure.call_args.kwargs['lexical_only'])

    def test_known_incompatible_pg_snapshot_is_blocked_without_affecting_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);policy={'fixture':{'source':str(root),'worktrees_root':str(root/'trees'),'blocked_embedding_snapshots':['legacy']}}
            cfg={'search':{'baseline':{'backend':'postgres','workspace_code':{'snapshot_id':'legacy'}}}}
            with self.assertRaisesRegex(ValueError,'incompatible snapshot'):
                validate_embedding_snapshot(root,cfg,policy)
            cfg['search']['baseline']['backend']='sqlite'
            validate_embedding_snapshot(root,cfg,policy)
            cfg['search']['baseline'].update(backend='postgres',workspace_code={'snapshot_id':'audited'})
            validate_embedding_snapshot(root,cfg,policy)

    def test_automatic_shared_selection_needs_audited_explicit_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);policy={'fixture':{'source':str(root),'worktrees_root':str(root/'trees'),'blocked_embedding_snapshots':['legacy']}}
            with self.assertRaisesRegex(ValueError,'explicit audited snapshot'):
                validate_embedding_snapshot(root,{'search':{'baseline':{'backend':'postgres'}}},policy)

    def test_launch_refused_before_reading_provider_credentials(self):
        with patch("mcp_profile.enforce_baseline_launch_policy", side_effect=ValueError("paused")), patch("mcp_profile.read_env") as read:
            with self.assertRaisesRegex(ValueError, "paused"):
                command_for("bsl", ["--profile", "workspace"], {}, inherited={})
            read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
