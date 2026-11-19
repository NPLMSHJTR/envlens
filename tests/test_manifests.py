"""Unit tests for manifest extraction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from envlens.manifests import discover, extract_env_sections, parse_manifest

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo-service"


class EnvSectionTests(unittest.TestCase):
    def test_compose_mapping_form(self) -> None:
        text = (
            "services:\n"
            "  app:\n"
            "    environment:\n"
            '      A: "1"\n'
            "      B: 2\n"
            "    ports:\n"
            '      - "8000:8000"\n'
        )
        keys, unknown = extract_env_sections(text)
        self.assertEqual(keys, {"A", "B"})
        self.assertFalse(unknown)

    def test_compose_list_forms(self) -> None:
        text = "    environment:\n      - A\n      - B=2\n      - C=${C:-default}\n"
        keys, _ = extract_env_sections(text)
        self.assertEqual(keys, {"A", "B", "C"})

    def test_kubernetes_ignores_structural_keys(self) -> None:
        text = (
            "      containers:\n"
            "        - name: app\n"
            "          env:\n"
            "            - name: A\n"
            '              value: "1"\n'
            "            - name: B\n"
            "              valueFrom:\n"
            "                secretKeyRef:\n"
            "                  name: secrets\n"
            "                  key: b\n"
        )
        keys, unknown = extract_env_sections(text)
        self.assertEqual(keys, {"A", "B"})
        self.assertFalse(unknown)

    def test_env_from_marks_unknown(self) -> None:
        text = "      envFrom:\n        - configMapRef:\n            name: shared\n"
        keys, unknown = extract_env_sections(text)
        self.assertEqual(keys, set())
        self.assertTrue(unknown)


class ManifestParsingTests(unittest.TestCase):
    def test_compose_interpolation_and_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / ".env.compose").write_text("WORKER_CONCURRENCY=4\n", encoding="utf-8")
            text = (
                "services:\n"
                "  app:\n"
                "    env_file:\n"
                "      - .env.compose\n"
                "    environment:\n"
                "      - DATABASE_URL\n"
                "      - REDIS_URL=${REDIS_URL:-redis://cache}\n"
            )
            scan = parse_manifest(text, "docker-compose.yml", "compose", base)
            self.assertEqual(set(scan.keys), {"DATABASE_URL", "REDIS_URL", "WORKER_CONCURRENCY"})
            self.assertEqual(scan.runtime_files, ["docker-compose.yml"])
            self.assertEqual(scan.unknown, [])

    def test_missing_env_file_is_unknown_not_empty(self) -> None:
        text = "services:\n  app:\n    env_file:\n      - .env.missing\n"
        scan = parse_manifest(text, "docker-compose.yml", "compose", Path("."))
        self.assertTrue(scan.unknown)
        self.assertEqual(scan.keys, {})

    def test_dockerfile_arguments_and_env(self) -> None:
        text = "FROM python:3.13-slim\nARG BUILD_VERSION\nENV APP_HOME=/app\n"
        scan = parse_manifest(text, "Dockerfile", "dockerfile", Path("."))
        self.assertEqual(set(scan.keys), {"BUILD_VERSION", "APP_HOME"})

    def test_workflow_secrets_are_ci_only(self) -> None:
        text = (
            "jobs:\n"
            "  test:\n"
            "    env:\n"
            '      CI: "true"\n'
            "    steps:\n"
            "      - run: test\n"
            "        env:\n"
            "          TOKEN: ${{ secrets.TOKEN }}\n"
        )
        scan = parse_manifest(text, ".github/workflows/ci.yml", "ci", Path("."))
        self.assertEqual(set(scan.ci_keys), {"CI", "TOKEN"})
        self.assertEqual(scan.keys, {})


class DiscoveryTests(unittest.TestCase):
    def test_demo_repository_is_fully_recognised(self) -> None:
        scan = discover(DEMO, ["."], [])
        self.assertEqual(len(scan.runtime_files), 3)
        self.assertIn("LOG_LEVEL", scan.keys)
        self.assertIn("WORKER_CONCURRENCY", scan.keys)
        self.assertIn("DATABASE_URL", scan.keys)
        self.assertIn("SENTRY_DSN", scan.ci_keys)
        self.assertNotIn("SENTRY_DSN", scan.keys)
        self.assertEqual(scan.unknown, [])


if __name__ == "__main__":
    unittest.main()
