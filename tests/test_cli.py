"""CLI contract tests: exit codes, output formats, and the repairing commands."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from envlens.cli import main

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent / "examples" / "demo-service"


def run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class CheckCommandTests(unittest.TestCase):
    def test_json_output_is_machine_readable(self) -> None:
        code, out, _ = run(["check", "--root", str(DEMO), "--format", "json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["summary"]["error"], 13)
        self.assertEqual(payload["summary"]["warning"], 5)
        self.assertEqual(payload["summary"]["files_scanned"], 5)
        self.assertEqual(len(payload["coverage"]["dynamic"]), 2)

    def test_fail_on_never_returns_zero(self) -> None:
        code, _, _ = run(["check", "--root", str(DEMO), "--fail-on", "never"])
        self.assertEqual(code, 0)

    def test_fail_on_warning_returns_one_on_warnings_only(self) -> None:
        fixture = HERE / "fixtures" / "case"
        self.assertEqual(run(["check", "--root", str(fixture)])[0], 0)
        self.assertEqual(run(["check", "--root", str(fixture), "--fail-on", "warning"])[0], 1)

    def test_github_annotations_point_at_the_line(self) -> None:
        code, out, _ = run(["check", "--root", str(DEMO), "--format", "github"])
        self.assertEqual(code, 1)
        self.assertIn("::error file=src/app.py,line=9", out)
        self.assertIn("missing-from-example", out)

    def test_unknown_path_is_a_usage_error(self) -> None:
        code, _, err = run(["check", "--root", str(DEMO), "does-not-exist"])
        self.assertEqual(code, 2)
        self.assertIn("does not exist", err)

    def test_root_must_be_a_directory(self) -> None:
        code, _, err = run(["check", "--root", str(DEMO / "README.md")])
        self.assertEqual(code, 2)
        self.assertIn("not a directory", err)

    def test_text_output_has_summary_and_coverage(self) -> None:
        _, out, _ = run(["check", "--root", str(DEMO), "--color", "never"])
        self.assertIn("13 errors", out)
        self.assertIn("5 files scanned", out)
        self.assertIn("dynamic access", out)


class RepairCommandTests(unittest.TestCase):
    def test_init_creates_contract_then_refuses_to_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text('import os\nA = os.environ["NEW_KEY"]\n', encoding="utf-8")
            code, _, _ = run(["init", "--root", str(root)])
            self.assertEqual(code, 0)
            content = (root / ".env.example").read_text(encoding="utf-8")
            self.assertIn("NEW_KEY=", content)
            self.assertIn("# used in app.py:2", content)

            code, _, err = run(["init", "--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("--force", err)

            code, _, _ = run(["init", "--root", str(root), "--force"])
            self.assertEqual(code, 0)

    def test_fix_appends_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text("OLD=1\n", encoding="utf-8")
            (root / "app.py").write_text(
                'import os\nOLD = os.environ["OLD"]\nNEW = os.environ["NEW"]\n',
                encoding="utf-8",
            )
            code, _, _ = run(["fix", "--root", str(root)])
            self.assertEqual(code, 0)
            content = (root / ".env.example").read_text(encoding="utf-8")
            self.assertTrue(content.startswith("OLD=1\n"))
            self.assertIn("NEW=", content)
            self.assertEqual(content.count("NEW="), 1)

            code, out, _ = run(["fix", "--root", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("already documents", out)
            self.assertEqual((root / ".env.example").read_text(encoding="utf-8").count("NEW="), 1)

    def test_fix_without_contract_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run(["fix", "--root", tmp])
            self.assertEqual(code, 2)
            self.assertIn("envlens init", err)


class ExplainCommandTests(unittest.TestCase):
    def test_healthy_variable(self) -> None:
        code, out, _ = run(["explain", "DATABASE_URL", "--root", str(DEMO)])
        self.assertEqual(code, 0)
        self.assertIn("declared", out)
        self.assertIn("read in code", out)
        self.assertIn("provisioned", out)
        self.assertIn("status       ok", out)

    def test_variable_with_error(self) -> None:
        code, out, _ = run(["explain", "STRIPE_SECRET_KEY", "--root", str(DEMO)])
        self.assertEqual(code, 1)
        self.assertIn("secret-in-example", out)

    def test_unknown_variable(self) -> None:
        code, _, err = run(["explain", "NO_SUCH_KEY", "--root", str(DEMO)])
        self.assertEqual(code, 1)
        self.assertIn("no evidence", err)


if __name__ == "__main__":
    unittest.main()
