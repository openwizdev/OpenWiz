from pathlib import Path
import struct
import unittest


class MarketTargetTest(unittest.TestCase):
    def test_targets(self):
        folder = Path(__file__).parent
        for name, width in (("phone", 390), ("desktop", 1440)):
            with self.subTest(target=name):
                image = folder / f"{name}.png"
                self.assertTrue(image.is_file(), f"{image.name} is missing")
                with image.open("rb") as source:
                    header = source.read(24)
                self.assertEqual(header[:16], b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
                self.assertEqual(struct.unpack(">I", header[16:20])[0], width)


if __name__ == "__main__":
    unittest.main()
