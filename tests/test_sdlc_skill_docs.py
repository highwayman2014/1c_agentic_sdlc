from pathlib import Path
import re
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1] / '.agents/skills/av-1c-agentic-sdlc'


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



if __name__ == '__main__':
    unittest.main()
