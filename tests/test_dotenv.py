"""Unit tests for the dotenv reader."""

from __future__ import annotations

import unittest
from pathlib import Path

from envlens.dotenv import looks_like_placeholder, parse_dotenv


def parse(text: str):
    return parse_dotenv(text, Path("sample.env"))


class DotenvParsingTests(unittest.TestCase):
    def test_basic_assignment_and_export(self) -> None:
        doc = parse("A=1\nexport B=2\n")
        self.assertEqual([entry.key for entry in doc.kv_entries], ["A", "B"])
        self.assertEqual([entry.value for entry in doc.kv_entries], ["1", "2"])

    def test_comments_and_blank_lines_are_classified(self) -> None:
        doc = parse("# a comment\n\nA=1\n")
        self.assertEqual([entry.kind for entry in doc.entries], ["comment", "blank", "kv"])

    def test_single_quotes_are_literal(self) -> None:
        doc = parse("A='a # b'\n")
        self.assertEqual(doc.kv_entries[0].value, "a # b")

    def test_double_quotes_expand_escapes(self) -> None:
        doc = parse('A="line\\nnext\\tend"\n')
        self.assertEqual(doc.kv_entries[0].value, "line\nnext\tend")

    def test_inline_comment_is_stripped_only_after_whitespace(self) -> None:
        self.assertEqual(parse("A=1 # note\n").kv_entries[0].value, "1")
        self.assertEqual(parse("A=a#b\n").kv_entries[0].value, "a#b")

    def test_multiline_double_quoted_value(self) -> None:
        doc = parse('CERT="first\nsecond"\nAFTER=2\n')
        self.assertEqual(doc.kv_entries[0].value, "first\nsecond")
        self.assertEqual(doc.kv_entries[1].key, "AFTER")
        self.assertEqual(doc.kv_entries[1].line, 3)

    def test_unterminated_quote_does_not_crash(self) -> None:
        doc = parse('A="first\nB=2')
        self.assertEqual(len(doc.kv_entries), 1)
        self.assertIn("B=2", doc.kv_entries[0].value or "")

    def test_empty_and_equals_in_value(self) -> None:
        doc = parse("A=\nB=a=b\n")
        self.assertEqual(doc.kv_entries[0].value, "")
        self.assertEqual(doc.kv_entries[1].value, "a=b")

    def test_invalid_lines(self) -> None:
        doc = parse("not an assignment\n1BAD=x\n=empty\n")
        self.assertEqual(len(doc.invalid_entries()), 3)
        self.assertEqual(doc.kv_entries, [])

    def test_duplicates_keep_both_lines(self) -> None:
        doc = parse("A=1\nA=2\n")
        duplicates = doc.duplicates()
        self.assertEqual(list(duplicates), ["A"])
        self.assertEqual([entry.line for entry in duplicates["A"]], [1, 2])

    def test_crlf_and_bom(self) -> None:
        doc = parse("\ufeffA=1\r\nB=2\r\n")
        self.assertEqual(doc.keys(), ["A", "B"])
        self.assertEqual(doc.kv_entries[0].value, "1")

    def test_placeholder_heuristic(self) -> None:
        self.assertTrue(looks_like_placeholder(""))
        self.assertTrue(looks_like_placeholder("your-key-here"))
        self.assertTrue(looks_like_placeholder("changeme"))
        self.assertFalse(looks_like_placeholder("sk_live_51H8xQ2eZvKYlo2C"))


if __name__ == "__main__":
    unittest.main()
