import re
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TargetPackage(unittest.TestCase):
    def test_brief_and_prompt(self):
        brief = (ROOT / "README.md").read_text()
        prompt = (ROOT / "prompt.md").read_text()
        self.assertRegex(brief, r"WizSite/blob/[0-9a-f]{40}/site\.css")
        for heading in ("Search states", "Code containment", "Image review"):
            self.assertIn(f"## {heading}", brief)
        for text in ("Preview a sample", "Create a preview", "Check the output",
                     "sample preview", "Search docs", "No pages match",
                     "Output reference", "fixtures/synthetic/reports/preview/"):
            with self.subTest(text=text):
                self.assertIn(text, brief)
                self.assertIn(text, prompt)
        for path in ("README.md", "prompt.md"):
            self.assertIsNone(re.search(r"^\s*[`~]{3,}", (ROOT / path).read_text(), re.M))

    def test_target_dimensions_and_links(self):
        for width in (390, 1440):
            with self.subTest(width=width):
                name = f"target-{width}.png"
                with (ROOT / name).open("rb") as image:
                    header = image.read(24)
                self.assertEqual(header[:16], b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
                self.assertEqual(struct.unpack(">I", header[16:20])[0], width)
                self.assertIn(f"]({name})", (ROOT / "README.md").read_text())


if __name__ == "__main__":
    unittest.main()
