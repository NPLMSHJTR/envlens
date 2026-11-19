"""Unit tests for language scanners and file walking."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from envlens.scanner import MAX_FILE_BYTES, language_for, scan_paths, scan_text


def keys(text: str, language: str) -> list[str]:
    refs, _ = scan_text(text, "sample", language)
    return sorted({ref.key for ref in refs})


class LanguageScannerTests(unittest.TestCase):
    def test_python_literals(self) -> None:
        text = (
            "import os\n"
            'A = os.environ["A"]\n'
            'B = os.environ.get("B")\n'
            'C = os.getenv("C", "x")\n'
            'os.environ.setdefault("D", "1")\n'
        )
        self.assertEqual(keys(text, "Python"), ["A", "B", "C", "D"])

    def test_python_dynamic_access(self) -> None:
        text = 'import os\nname = "A"\nvalue = os.environ[name]\n'
        refs, dynamic = scan_text(text, "sample.py", "Python")
        self.assertEqual(refs, [])
        self.assertEqual(len(dynamic), 1)

    def test_javascript_forms(self) -> None:
        text = (
            "const a = process.env.A;\n"
            'const b = process.env["B"];\n'
            "const { C, D } = process.env;\n"
            "const e = import.meta.env.VITE_E;\n"
        )
        self.assertEqual(keys(text, "TypeScript"), ["A", "B", "C", "D", "VITE_E"])

    def test_javascript_dynamic_access(self) -> None:
        text = 'const key = "A";\nconst v = process.env[key];\n'
        _, dynamic = scan_text(text, "sample.js", "JavaScript")
        self.assertEqual(len(dynamic), 1)

    def test_other_languages(self) -> None:
        self.assertEqual(keys('os.Getenv("GO_KEY")', "Go"), ["GO_KEY"])
        self.assertEqual(keys('os.LookupEnv("LOOK_KEY")', "Go"), ["LOOK_KEY"])
        self.assertEqual(keys('env::var("RUST_KEY")', "Rust"), ["RUST_KEY"])
        self.assertEqual(keys('ENV["RUBY_KEY"]', "Ruby"), ["RUBY_KEY"])
        self.assertEqual(keys("getenv('PHP_KEY')", "PHP"), ["PHP_KEY"])
        self.assertEqual(keys('System.getenv("JAVA_KEY")', "Java"), ["JAVA_KEY"])
        self.assertEqual(keys('Environment.GetEnvironmentVariable("CS_KEY")', "C#"), ["CS_KEY"])

    def test_languages_beyond_the_python_and_javascript_ecosystems(self) -> None:
        self.assertEqual(
            keys('ProcessInfo.processInfo.environment["SWIFT_KEY"]', "Swift"), ["SWIFT_KEY"]
        )
        self.assertEqual(keys("Platform.environment['DART_KEY']", "Dart"), ["DART_KEY"])
        self.assertEqual(
            keys("const host = String.fromEnvironment('DART_DEFINE');", "Dart"),
            ["DART_DEFINE"],
        )
        self.assertEqual(keys('System.get_env("ELIXIR_KEY")', "Elixir"), ["ELIXIR_KEY"])
        self.assertEqual(keys('sys.env("SCALA_KEY")', "Scala"), ["SCALA_KEY"])
        self.assertEqual(keys('std::getenv("CPP_KEY")', "C/C++"), ["CPP_KEY"])
        self.assertEqual(keys('os.getenv("LUA_KEY")', "Lua"), ["LUA_KEY"])
        self.assertEqual(keys('Sys.getenv("R_KEY")', "R"), ["R_KEY"])
        self.assertEqual(keys('ENV["JULIA_KEY"]', "Julia"), ["JULIA_KEY"])
        self.assertEqual(keys("my $v = $ENV{PERL_KEY};", "Perl"), ["PERL_KEY"])
        self.assertEqual(keys('(System/getenv "CLJ_KEY")', "Clojure"), ["CLJ_KEY"])
        self.assertEqual(keys('Deno.env.get("DENO_KEY")', "TypeScript"), ["DENO_KEY"])
        self.assertEqual(keys("const k = Bun.env.BUN_KEY;", "JavaScript"), ["BUN_KEY"])

    def test_dynamic_access_in_new_languages(self) -> None:
        _, swift_dynamic = scan_text(
            "let v = ProcessInfo.processInfo.environment[key]", "a.swift", "Swift"
        )
        self.assertEqual(len(swift_dynamic), 1)
        _, dart_dynamic = scan_text("final v = Platform.environment[key];", "a.dart", "Dart")
        self.assertEqual(len(dart_dynamic), 1)

    def test_ignore_marker_inline_and_on_previous_line(self) -> None:
        inline = 'A = os.environ["SKIP_ME"]  # envlens:ignore\n'
        self.assertEqual(keys(inline, "Python"), [])
        previous = '# envlens:ignore\nA = os.environ["SKIP_ME"]\n'
        self.assertEqual(keys(previous, "Python"), [])

    def test_language_lookup(self) -> None:
        self.assertEqual(language_for(Path("a.py")), "Python")
        self.assertEqual(language_for(Path("a.tsx")), "TypeScript")
        self.assertIsNone(language_for(Path("a.md")))


class WalkTests(unittest.TestCase):
    def test_coverage_counts_binary_and_large_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.py").write_text('import os\nA = os.environ["A"]\n', encoding="utf-8")
            (root / "image.py").write_bytes(b"\x00\x01\x02")
            (root / "big.py").write_text("#" * (MAX_FILE_BYTES + 10), encoding="utf-8")
            used, coverage = scan_paths(root, ["."], [])

            self.assertIn("A", used)
            self.assertEqual(coverage.files_scanned, 1)
            self.assertEqual(coverage.skipped.get("binary"), 1)
            self.assertEqual(coverage.skipped.get("too-large"), 1)
            self.assertEqual(coverage.languages.get("Python"), 1)

    def test_explicit_target_overrides_exclude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text('import os\nA = os.environ["A"]\n', encoding="utf-8")
            used, _ = scan_paths(root, ["."], ["app.py"])
            self.assertEqual(used, {})
            used, _ = scan_paths(root, ["app.py"], ["app.py"])
            self.assertIn("A", used)

    def test_virtual_environment_is_pruned_by_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text('import os\nA = os.environ["A"]\n', encoding="utf-8")
            venv = root / ".venv-check" / "Lib" / "site-packages"
            venv.mkdir(parents=True)
            (root / ".venv-check" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
            (venv / "dependency.py").write_text(
                'import os\nB = os.environ["FROM_DEPENDENCY"]\n', encoding="utf-8"
            )
            used, coverage = scan_paths(root, ["."], [])
            self.assertIn("A", used)
            self.assertNotIn("FROM_DEPENDENCY", used)
            self.assertEqual(coverage.files_scanned, 1)


if __name__ == "__main__":
    unittest.main()
