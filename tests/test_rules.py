"""Rule-level tests against the demo repository and the small fixtures."""

from __future__ import annotations

import unittest
from pathlib import Path

from envlens.rules import Options, audit

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent / "examples" / "demo-service"
FIXTURES = HERE / "fixtures"


def keys_for(report, rule: str) -> set[str]:
    return {finding.key for finding in report.findings if finding.rule == rule}


class DemoServicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = audit(Options(root=DEMO))

    def test_missing_from_example(self) -> None:
        self.assertEqual(
            keys_for(self.report, "missing-from-example"),
            {
                "SENTRY_DSN",
                "PROFILE_NAME",
                "OTEL_ENDPOINT",
                "PARTNER_TOKEN",
                "LOG_LEVEL",
                "GITHUB_TOKEN",
                "WORKER_CONCURRENCY",
            },
        )

    def test_unprovisioned(self) -> None:
        self.assertEqual(
            keys_for(self.report, "unprovisioned"),
            {"SENTRY_DSN", "PROFILE_NAME", "OTEL_ENDPOINT", "STRIPE_SECRET_KEY", "PARTNER_TOKEN"},
        )

    def test_contract_and_local_drift(self) -> None:
        self.assertEqual(keys_for(self.report, "unused-in-code"), {"LEGACY_FLAG"})
        self.assertEqual(
            keys_for(self.report, "local-missing"), {"LEGACY_FLAG", "STRIPE_SECRET_KEY"}
        )
        self.assertEqual(keys_for(self.report, "local-extra"), {"SENTRY_DSN", "LOCAL_ONLY"})

    def test_credential_shaped_value(self) -> None:
        self.assertEqual(keys_for(self.report, "secret-in-example"), {"STRIPE_SECRET_KEY"})

    def test_counts_and_coverage(self) -> None:
        counts = self.report.counts()
        self.assertEqual(counts["error"], 13)
        self.assertEqual(counts["warning"], 5)
        self.assertEqual(self.report.coverage.files_scanned, 5)
        self.assertEqual(len(self.report.coverage.dynamic), 2)

    def test_every_finding_has_a_location(self) -> None:
        for finding in self.report.findings:
            if finding.rule == "case-collision":
                continue
            self.assertIsNotNone(finding.file, msg=finding)
            self.assertIsNotNone(finding.line, msg=finding)


class FixtureTests(unittest.TestCase):
    def test_clean_repository_has_no_findings(self) -> None:
        report = audit(Options(root=FIXTURES / "clean"))
        self.assertEqual(report.findings, [])
        self.assertEqual(report.notes, [])

    def test_duplicates_and_prose(self) -> None:
        report = audit(Options(root=FIXTURES / "dup"))
        self.assertEqual(keys_for(report, "duplicate-key"), {"FOO"})
        self.assertEqual(len(keys_for(report, "invalid-line")), 1)
        self.assertEqual(report.counts()["error"], 0)

    def test_case_collision(self) -> None:
        report = audit(Options(root=FIXTURES / "case"))
        self.assertEqual(keys_for(report, "case-collision"), {"FOO", "foo"})
        self.assertEqual(keys_for(report, "unused-in-code"), {"foo"})

    def test_unreadable_env_file_suppresses_provisioning_rule(self) -> None:
        report = audit(Options(root=FIXTURES / "compose-unreadable"))
        self.assertEqual(keys_for(report, "unprovisioned"), set())
        self.assertTrue(any("provisioning check skipped" in note for note in report.notes))

    def test_ignore_patterns_remove_findings(self) -> None:
        report = audit(Options(root=DEMO, ignore=["SENTRY_*"]))
        for rule in ("missing-from-example", "unprovisioned", "local-extra"):
            self.assertNotIn("SENTRY_DSN", keys_for(report, rule))

    def test_missing_example_is_reported_as_note(self) -> None:
        report = audit(Options(root=FIXTURES / "case", example_files=["nope.env"]))
        self.assertTrue(any("not found" in note for note in report.notes))

    def test_manifest_analysis_can_be_disabled(self) -> None:
        report = audit(Options(root=DEMO, manifests=False))
        self.assertEqual(keys_for(report, "unprovisioned"), set())
        self.assertTrue(any("manifest analysis disabled" in note for note in report.notes))


if __name__ == "__main__":
    unittest.main()
