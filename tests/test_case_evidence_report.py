import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

SKILL = Path(__file__).resolve().parents[1] / '.agents/skills/av-1c-agentic-sdlc'
SCRIPT = SKILL / 'scripts/case_evidence_report.py'
spec = importlib.util.spec_from_file_location('case_evidence_report', SCRIPT)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def png_chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))


class EvidenceReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'screenshots').mkdir()
        raw = (b'\x89PNG\r\n\x1a\n'
               + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 120, 100, 8, 2, 0, 0, 0))
               + png_chunk(b'IDAT', zlib.compress((b'\0' + b'\xff' * 360) * 100))
               + png_chunk(b'IEND', b''))
        (self.root / 'screenshots/fixture.png').write_bytes(raw)
        self.manifest = {
            'schema_version': 1, 'case_id': 'fixture', 'title': 'Проверка пакета',
            'generated_at': '2026-01-01T00:00:00Z', 'verdict': 'Тестовая фикстура, не проверка ИБ',
            'scope': ['Сборка отчёта'], 'limitations': ['Без обращения к 1С'],
            'environments': [{'id': 'dev', 'name': 'Фикстура', 'ref': 'fixture',
                              'connection': 'fixture', 'profile': 'fixture'}],
            'checks': [{'title': 'Манифест', 'status': 'passed', 'evidence': 'Unit fixture'}],
            'links': [{'id': 'link', 'environment': 'dev', 'label': 'Объект',
                       'navigation_link': 'e1cib/data/Document.Fixture?ref=' + '0' * 32,
                       'verified_open': True}],
            'screenshots': [{'id': 'shot', 'title': '<Кадр>', 'environment': 'dev',
                             'link_id': 'link', 'path': 'screenshots/fixture.png',
                             'sha256': hashlib.sha256(raw).hexdigest(),
                             'captured_at': '2026-01-01T00:00:00Z', 'visual_review': 'passed',
                             'observations': ['Тестовый PNG']}],
        }

    def test_portable_html_escapes_text_and_marks_limits(self):
        html = report.render(self.manifest, self.root)
        self.assertIn('&lt;Кадр&gt;', html)
        self.assertIn('screenshots/fixture.png', html)
        self.assertIn('С ограничениями', html)
        self.assertNotIn(str(self.root), html)
        self.assertNotIn('<script', html.lower())

    def test_wrong_hash_is_rejected(self):
        self.manifest['screenshots'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            report.validate(self.manifest, self.root)

    def test_outside_or_absolute_assets_are_rejected(self):
        for path in ['../outside.png', '/outside.png', 'C:/outside.png']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                report.local_asset(self.root, path)

    def test_link_environment_and_review_are_required(self):
        for section, field, value in [('screenshots', 'environment', 'other'),
                                      ('screenshots', 'visual_review', 'pending'),
                                      ('links', 'verified_open', False)]:
            data = copy.deepcopy(self.manifest)
            data[section][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                report.validate(data, self.root)

    def test_secret_fields_and_credential_urls_are_rejected(self):
        for value in [{'password': 'fixture'}, {'extra': 'https://user:pass@example.invalid'}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                report.check_secrets(value)

    def test_cli_check_writes_nothing_and_render_stays_beside_manifest(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')
        command = [sys.executable, str(SCRIPT), str(manifest)]
        checked = subprocess.run(command + ['--check'], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertFalse((self.root / 'report.html').exists())
        rendered = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertTrue((self.root / 'report.html').is_file())


if __name__ == '__main__':
    unittest.main()
