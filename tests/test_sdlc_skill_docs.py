from pathlib import Path
import re
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1] / '.agents/skills/av-1c-agentic-sdlc'
TEMPORARY = ROOT / 'references/temporary-bsl-pg.md'


def heading_anchor(text):
    text = re.sub(r'[^\w\s-]', '', text.lower()).strip()
    return re.sub(r'\s', '-', text)


class SkillDocumentationTests(unittest.TestCase):
    def test_relative_markdown_links_and_anchors_resolve(self):
        for source in ROOT.rglob('*.md'):
            text = source.read_text(encoding='utf-8-sig')
            for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
                if '://' in link or link.startswith('mailto:'):
                    continue
                path, _, anchor = unquote(link).partition('#')
                target = (source.parent / path).resolve() if path else source
                with self.subTest(source=str(source.relative_to(ROOT)), link=link):
                    self.assertTrue(target.exists(), 'Missing reference: ' + str(target))
                    if anchor and target.is_file():
                        headings = re.findall(r'^#{1,6}\s+(.+)$', target.read_text(encoding='utf-8-sig'), re.M)
                        self.assertIn(anchor, [heading_anchor(h) for h in headings])

    def test_local_executable_workaround_has_one_disclosed_home(self):
        references = []
        special_tokens = ['pg-bg2', 'unified_workspace_applications', '/issues/810', '/issues/811']
        for source in ROOT.rglob('*.md'):
            text = source.read_text(encoding='utf-8-sig')
            if source != TEMPORARY:
                for token in special_tokens:
                    self.assertNotIn(token, text, str(source.relative_to(ROOT)))
            if 'temporary-bsl-pg.md' in text:
                references.append(source.relative_to(ROOT).as_posix())
        if TEMPORARY.is_file():
            self.assertEqual(references, ['references/mcp-setup.md'])
            self.assertIn('## Верни официальный релиз', TEMPORARY.read_text(encoding='utf-8'))
        else:
            self.assertEqual(references, [], 'Retired workaround must have no remaining pointer')


if __name__ == '__main__':
    unittest.main()
