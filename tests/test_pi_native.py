import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from migrate_pi_native import convert_server, migrate, without_adapter


class NativePiTests(unittest.TestCase):
    def test_credentials_filters_and_timeout_survive_conversion(self):
        result = convert_server({"url": "http://127.0.0.1:1933/mcp",
            "headers": {"Authorization": "fixture-private"}, "lifecycle": "lazy",
            "requestTimeoutMs": 180000, "includeTools": ["find", "read"],
            "directTools": ["find", "delete"], "excludeTools": ["read"]})
        self.assertEqual(result["headers"]["Authorization"], "fixture-private")
        self.assertEqual(result["timeout"], 180)
        self.assertEqual(result["toolExposure"], {"find": "direct", "read": "hidden", "*": "hidden"})
        self.assertNotIn("lifecycle", result)
        self.assertNotIn("requestTimeoutMs", result)

    def test_native_enabled_and_unrelated_packages_preserved(self):
        old = {"model": "unchanged", "packages": ["npm:pi-mcp-adapter", "npm:wiki"],
               "extensions": ["-builtin:mcp", "other.ts"]}
        new = without_adapter(old)
        self.assertEqual(old["packages"][0], "npm:pi-mcp-adapter")
        self.assertEqual(new["packages"], ["npm:wiki"])
        self.assertEqual(new["extensions"], ["other.ts", "builtin:mcp"])
        self.assertEqual(new["model"], "unchanged")
        self.assertEqual(without_adapter(new), new)

    def test_migration_preserves_native_entries_and_keeps_old_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            legacy = home / ".config/mcp/mcp.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({"mcpServers": {"old": {"command": "old"}, "keep": {"command": "legacy"}}}))
            agent = home / ".pi/agent"
            agent.mkdir(parents=True)
            (agent / "mcp.json").write_text(json.dumps({"mcpServers": {"keep": {"command": "native"}}}))
            (agent / "settings.json").write_text(json.dumps({"packages": ["npm:pi-mcp-adapter"]}))
            # Place backups in the isolated home as well.
            with patch("pathlib.Path.home", return_value=home), patch("builtins.print"):
                defaults = {"keep": {"command": "default"}, "base": {"command": "reference"}}
                migrate(home, apply=True, defaults=defaults)
                first = (agent / "mcp.json").read_text()
                migrate(home, apply=True, defaults=defaults)
            self.assertEqual(first, (agent / "mcp.json").read_text())
            self.assertEqual(json.loads(first)["mcpServers"]["keep"]["command"], "native")
            self.assertEqual(json.loads(first)["mcpServers"]["base"]["command"], "reference")
            self.assertTrue(legacy.exists())
            self.assertTrue(list((home / ".config/1c-agentic-sdlc/backups").rglob("settings.json")))

    def test_unknown_options_stop_before_settings_change(self):
        with self.assertRaises(ValueError):
            convert_server({"command": "x", "bearerCommand": "special-auth"})
        with self.assertRaises(ValueError):
            convert_server({"command": "x", "includeTools": ["read_*"]})

    def test_migration_does_not_restore_wiki_mcp_from_any_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            legacy = home / ".config/mcp/mcp.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({"mcpServers": {
                "llm-wiki-project": {"command": "old-wiki"}, "other": {"command": "keep"}}}))
            agent = home / ".pi/agent"
            agent.mkdir(parents=True)
            (agent / "mcp.json").write_text(json.dumps({"mcpServers": {"llm-wiki-personal": {"command": "old"}}}))
            (agent / "settings.json").write_text(json.dumps({"packages": ["npm:@zosmaai/pi-llm-wiki"]}))
            with patch("pathlib.Path.home", return_value=home), patch("builtins.print"):
                migrate(home, apply=True, defaults={"llm-wiki-project": {"command": "default-wiki"}})
            result = json.loads((agent / "mcp.json").read_text())["mcpServers"]
            self.assertEqual(set(result), {"other"})
            self.assertIn("npm:@zosmaai/pi-llm-wiki", json.loads((agent / "settings.json").read_text())["packages"])


if __name__ == "__main__":
    unittest.main()
