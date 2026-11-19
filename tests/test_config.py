"""Configuration loading tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from envlens.config import load_config


class ConfigTests(unittest.TestCase):
    def test_dedicated_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".envlens.toml").write_text(
                'ignore = ["SECRET_*"]\n'
                'exclude = ["vendor/**"]\n'
                'fail_on = "warning"\n'
                "manifests = false\n",
                encoding="utf-8",
            )
            config = load_config(root)
            self.assertEqual(config.ignore, ["SECRET_*"])
            self.assertEqual(config.exclude, ["vendor/**"])
            self.assertEqual(config.fail_on, "warning")
            self.assertFalse(config.manifests)
            self.assertEqual(config.source, ".envlens.toml")

    def test_pyproject_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[tool.envlens]\nexample_files = [".env.dist"]\n', encoding="utf-8"
            )
            config = load_config(root)
            self.assertEqual(config.example_files, [".env.dist"])
            self.assertIn("pyproject.toml", config.source or "")

    def test_unknown_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".envlens.toml").write_text('ignored = ["A"]\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(root)

    def test_absent_configuration_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            self.assertIsNone(config.source)
            self.assertEqual(config.ignore, [])


if __name__ == "__main__":
    unittest.main()
