import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from baseline_credentials import PROTOCOL, resolve
from mcp_profile import command_for, enforce_baseline_launch_policy


class BaselineTests(unittest.TestCase):
    def test_reader_protocol_and_url_encoding(self):
        request = {"protocol": PROTOCOL, "action": "resolve-url", "mode": "reader", "vault_role_base": "smm-auto-local"}
        profile = {"host": "127.0.0.1", "port": 15432, "database": "bsl_baseline"}
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

    def test_lexical_policy_removes_inherited_embedding_settings_without_reading_keys(self):
        inherited = {"EMBEDDING_URL": "https://provider.invalid", "EMBEDDING_API_KEY": "fixture",
                     "BSL_MCP_EFFECTIVE_EMBEDDING_QUERY_PREFIX": "frozen", "KEEP": "yes"}
        runtime = {"launcher": "shared.exe", "platform_help": "missing-help"}
        with patch("mcp_profile.enforce_baseline_launch_policy", return_value="lexical-only"), patch("mcp_profile.read_env") as read:
            command, env = command_for("bsl", ["--profile", "workspace"], runtime, inherited=inherited)
            self.assertEqual(env, {"KEEP": "yes"})
            self.assertEqual(command[0], "shared.exe")
            read.assert_not_called()

    def test_launch_refused_before_reading_provider_credentials(self):
        with patch("mcp_profile.enforce_baseline_launch_policy", side_effect=ValueError("paused")), patch("mcp_profile.read_env") as read:
            with self.assertRaisesRegex(ValueError, "paused"):
                command_for("bsl", ["--profile", "workspace"], {}, inherited={})
            read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
