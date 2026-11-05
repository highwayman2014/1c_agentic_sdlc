import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

SPEC = importlib.util.spec_from_file_location('case_evidence_report', Path(__file__).parents[1] / '.agents/skills/av-1c-agentic-sdlc/scripts/case_evidence_report.py')
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


def png():
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 120, 100, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\x00' + b'\xff' * 360) * 100)) + chunk(b'IEND', b'')


class EvidenceReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'screenshots').mkdir()
        image = png()
        (self.root / 'screenshots/one.png').write_bytes(image)
        self.manifest = {
            'schema_version': 1, 'case_id': 'TEST-1', 'title': 'Safe <report>', 'verdict': 'Passed <script>',
            'generated_at': '2026-11-03', 'scope': ['Read only'], 'limitations': ['No real cost'],
            'checks': [{'title': 'UI <check>', 'status': 'passed', 'evidence': 'VA MCP'}],
            'environments': [{'id': 'as', 'name': 'АС', 'ref': 'copy', 'connection': 'dev', 'profile': 'AS'}],
            'links': [{'id': 'one', 'label': 'Document', 'environment': 'as', 'navigation_link': 'e1cib/data/Документ.Тест?ref=1', 'verified_open': True}],
            'screenshots': [{'id': 'one', 'title': 'One', 'environment': 'as', 'link_id': 'one', 'path': 'screenshots/one.png',
                             'sha256': hashlib.sha256(image).hexdigest(), 'captured_at': '2026-11-03', 'visual_review': 'passed', 'observations': ['Visible field']}],
        }

    def test_valid_report(self):
        rendered = REPORT.render(self.manifest, self.root)
        self.assertIn('screenshots/one.png', rendered)
        self.assertIn('С ограничениями', rendered)

    def test_html_escaped(self):
        rendered = REPORT.render(self.manifest, self.root)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;report&gt;', rendered)

    def test_bad_hash(self):
        self.manifest['screenshots'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            REPORT.validate(self.manifest, self.root)

    def test_path_traversal(self):
        self.manifest['screenshots'][0]['path'] = '../other.png'
        with self.assertRaisesRegex(ValueError, 'escapes'):
            REPORT.validate(self.manifest, self.root)

    def test_windows_absolute_path(self):
        self.manifest['screenshots'][0]['path'] = 'C:/private/file.png'
        with self.assertRaisesRegex(ValueError, 'relative'):
            REPORT.validate(self.manifest, self.root)

    def test_unreviewed_image(self):
        self.manifest['screenshots'][0]['visual_review'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'visual review'):
            REPORT.validate(self.manifest, self.root)

    def test_environment_mismatch(self):
        self.manifest['screenshots'][0]['environment'] = 'bp'
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            REPORT.validate(self.manifest, self.root)

    def test_unverified_link(self):
        self.manifest['links'][0]['verified_open'] = False
        with self.assertRaisesRegex(ValueError, 'Unverified'):
            REPORT.validate(self.manifest, self.root)

    def test_unsafe_link(self):
        self.manifest['links'][0]['navigation_link'] = 'javascript:alert(1)'
        with self.assertRaisesRegex(ValueError, 'navigation'):
            REPORT.validate(self.manifest, self.root)

    def test_no_fake_image(self):
        (self.root / 'screenshots/one.png').write_text('placeholder')
        with self.assertRaisesRegex(ValueError, 'real PNG'):
            REPORT.validate(self.manifest, self.root)

    def test_no_empty_gallery(self):
        self.manifest['screenshots'] = []
        with self.assertRaisesRegex(ValueError, 'real screenshots'):
            REPORT.validate(self.manifest, self.root)

    def test_credentials_rejected(self):
        for extra in [{'password': 'fake'}, {'note': '/P"fake"'}, {'url': 'http://name:fake@localhost/'}]:
            with self.subTest(extra=extra):
                data = copy.deepcopy(self.manifest)
                data.update(extra)
                with self.assertRaises(ValueError):
                    REPORT.validate(data, self.root)

    def test_unknown_status_rejected(self):
        self.manifest['checks'][0]['status'] = 'success-ish'
        with self.assertRaisesRegex(ValueError, 'status'):
            REPORT.validate(self.manifest, self.root)


if __name__ == '__main__':
    unittest.main()
