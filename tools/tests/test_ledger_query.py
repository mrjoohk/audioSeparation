"""Meaningful CLI/API regression checks; run Python with -B to avoid caches."""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from ledger_query import LedgerError, query_ledger, render_markdown  # noqa: E402


class LedgerQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.path = self.folder / "edges.csv"
        self.header = ["id", "type", "severity", "title", "location", "status",
                       "fix_ref", "test_ref", "source_doc", "notes"]
        self.rows = [
            ["F-001", "finding", "high", "한글 인코딩", "src/a.py:8", "open",
             "D-002", "", "audit.md", "근거 D-002"],
            ["D-002", "decision", "", "UTF-8 결정", "rd/design.md", "verified",
             "", "test_utf8", "", "연결 M-003"],
            ["M-003", "mapping", "", "변환 매핑", "rd/map.md", "fixed",
             "F-001", "", "", "순환 및 없는 F-999"],
            ["F-004", "finding", "low", "인코딩 보류", "src/b.py", "deferred",
             "", "", "", "검토 대기"],
            ["F-005", "finding", "low", "별도 항목", "src/c.py", "open",
             "", "", "", "관계 없는 U F-001-extra 및 UF-001"],
            ["F-006", "finding", "low", "기각 항목", "src/d.py", "rejected",
             "", "", "", "오래된 UTF-8 제안"],
        ]
        self.write_rows(self.rows)

    def write_rows(self, rows, header=None, bom=False):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(self.header if header is None else header)
        writer.writerows(rows)
        self.path.write_text(buffer.getvalue(), encoding="utf-8-sig" if bom else "utf-8",
                             newline="")

    def cli(self, *args):
        env = dict(os.environ, PYTHONIOENCODING="ascii")
        return subprocess.run([sys.executable, "-B", str(TOOLS / "ledger_query.py"),
                               "--ledger", str(self.path), *args],
                              cwd=self.folder, env=env, capture_output=True, check=False)

    def test_default_open_projection_and_reproducible_source(self):
        raw = self.path.read_bytes()
        result = query_ledger(self.path)
        self.assertEqual([row["id"] for row in result["rows"]], ["F-001", "F-005"])
        self.assertEqual(result["filters"]["statuses"], ["open"])
        self.assertEqual(result["columns"], ["id", "status", "severity", "title", "location"])
        self.assertNotIn("notes", result["rows"][0])
        self.assertEqual(result["total"], 6)
        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["returned"], 2)
        self.assertEqual(result["source"]["path"], str(self.path.resolve()))
        self.assertEqual(result["source"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.path.read_bytes(), raw)

    def test_explicit_verified_id_ignores_default_open_and_reports_missing_ids(self):
        result = query_ledger(self.path, ids=["D-002", "F-999", "D-002"])
        self.assertEqual(result["filters"]["ids"], ["D-002", "F-999"])
        self.assertEqual(result["filters"]["statuses"], [])
        self.assertEqual(result["rows"][0]["status"], "verified")
        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["missing_ids"], ["F-999"])
        filtered = query_ledger(self.path, ids=["D-002"], statuses=["open"])
        self.assertEqual(filtered["returned"], 0)
        self.assertEqual(filtered["missing_ids"], [])

    def test_statuses_and_literal_casefold_search_are_combined(self):
        result = query_ledger(self.path, statuses=["verified", "rejected"], query="utf-8")
        self.assertEqual([row["id"] for row in result["rows"]], ["D-002", "F-006"])
        self.assertEqual(query_ledger(self.path, statuses=["all"], query="src/b.py")["returned"], 1)
        self.assertEqual(query_ledger(self.path, statuses=["open"], query="src/b.py")["returned"], 0)
        self.assertEqual(query_ledger(self.path, statuses=["all"], query=".*")["returned"], 0)

    def test_related_closure_handles_cycles_and_crosses_seed_status_filter(self):
        result = query_ledger(self.path, ids=["F-001"], statuses=["open"], related=True)
        self.assertEqual([row["id"] for row in result["rows"]], ["F-001", "D-002", "M-003"])
        self.assertEqual(result["seed_count"], 1)
        self.assertEqual(result["matched"], 3)
        self.assertEqual(result["related_mode"], "undirected-transitive")
        # Starting at the last node also reaches incoming references.
        reverse = query_ledger(self.path, ids=["M-003"], related=True)
        self.assertEqual([row["id"] for row in reverse["rows"]], ["F-001", "D-002", "M-003"])
        self.assertEqual(query_ledger(self.path, ids=["F-999"], related=True)["returned"], 0)

    def test_pagination_counts_all_matches_and_keeps_stable_source_order(self):
        first = query_ledger(self.path, statuses=["all"], limit=2)
        second = query_ledger(self.path, statuses=["all"], limit=2, offset=2)
        last = query_ledger(self.path, statuses=["all"], limit=2, offset=4)
        beyond = query_ledger(self.path, statuses=["all"], limit=2, offset=99)
        self.assertEqual(first["matched"], 6)
        self.assertEqual(first["returned"], 2)
        self.assertTrue(first["has_more"])
        self.assertTrue(first["truncated"])
        self.assertEqual(first["next_offset"], 2)
        self.assertEqual([row["id"] for row in second["rows"]], ["M-003", "F-004"])
        self.assertEqual(second["next_offset"], 4)
        self.assertFalse(last["has_more"])
        self.assertTrue(last["truncated"])
        self.assertIsNone(last["next_offset"])
        self.assertEqual(beyond["returned"], 0)
        self.assertFalse(beyond["has_more"])
        self.assertTrue(beyond["truncated"])
        self.assertEqual(first["source"]["sha256"], second["source"]["sha256"])

    def test_csv_bom_multiline_and_markdown_escaping_preserve_data(self):
        row = self.rows[0][:]
        row[-1] = "한글, 설명\n파이프 | 및 <tag> & `코드`"
        self.write_rows([row], bom=True)
        result = query_ledger(self.path, columns=["notes", "title"])
        self.assertEqual(result["columns"], ["id", "status", "notes", "title"])
        self.assertEqual(result["rows"][0]["notes"], row[-1])
        rendered = render_markdown(result)
        self.assertIn("한글, 설명<br>파이프 &#124; 및 &lt;tag&gt; &amp; `코드`", rendered)
        self.assertEqual(rendered.count("| ---"), 4)

    def test_cli_repeated_filters_and_utf8_stdout_even_with_ascii_environment(self):
        completed = self.cli("--status", "open", "--status", "deferred", "--query", "인코딩")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual([row["id"] for row in result["rows"]], ["F-001", "F-004"])
        self.assertIn("한글 인코딩", completed.stdout.decode("utf-8"))
        self.assertEqual(completed.stderr, b"")
        explicit = self.cli("--id", "D-002", "--id", "M-003")
        self.assertEqual([row["id"] for row in json.loads(explicit.stdout)["rows"]],
                         ["D-002", "M-003"])
        self.assertEqual(set(self.folder.iterdir()), {self.path})

    def test_cli_markdown_includes_pagination_and_selected_notes(self):
        completed = self.cli("--id", "D-002", "--format", "md", "--columns", "title,notes")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        rendered = completed.stdout.decode("utf-8")
        self.assertIn('"matched": 1', rendered)
        self.assertIn("| id | status | title | notes |", rendered)
        self.assertIn("| D-002 | verified | UTF-8 결정 | 연결 M-003 |", rendered)

    def test_header_only_ledger_is_valid_but_missing_headers_are_not(self):
        self.write_rows([], header=["id", "status"])
        self.assertEqual(query_ledger(self.path)["total"], 0)
        self.path.write_text("id,title\n", encoding="utf-8")
        with self.assertRaisesRegex(LedgerError, "Missing required columns: status"):
            query_ledger(self.path)

    def test_bad_sources_fail_without_partial_output_or_any_file_changes(self):
        bad_sources = [
            ("id,status\nF-001,open\nF-001,verified\n", "Duplicate ID"),
            ("id,status\nF-001,open\nF-002,\n", "Missing required value 'status'"),
            ("id,status\n,open\n", "Missing required value 'id'"),
            ('id,status,title\nF-001,open,"unterminated\n', "Invalid CSV"),
            ("id,status\nF-001,open,extra\n", "expected 2 fields, got 3"),
            ("id,status,title\nF-001,open\n", "expected 3 fields, got 2"),
            ("id,status,status\nF-001,open,open\n", "duplicate column name"),
            ("id,status,\nF-001,open,x\n", "empty column name"),
            ("id,status\nF-001,unknown\n", "Invalid status"),
            ("id,status\nF-001,open\nF-002, verified\n", "Whitespace around"),
            ("", "missing or empty column name"),
            ("id,status\nF-001,open\x00\n", "NUL"),
        ]
        for source, message in bad_sources:
            with self.subTest(message=message):
                self.path.write_text(source, encoding="utf-8")
                before = self.path.read_bytes()
                # Even an unrelated valid first row must not hide later corruption.
                completed = self.cli("--id", "F-001")
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, b"")
                error = json.loads(completed.stderr.decode("utf-8"))
                self.assertIn(message, error["error"]["message"])
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(set(self.folder.iterdir()), {self.path})

    def test_bad_encoding_missing_file_and_invalid_query_parameters(self):
        self.path.write_bytes(b"id,status\nF-001,open\n\xff")
        with self.assertRaisesRegex(LedgerError, "must be UTF-8"):
            query_ledger(self.path)
        with self.assertRaisesRegex(LedgerError, "Cannot read ledger"):
            query_ledger(self.folder / "missing.csv")
        self.write_rows(self.rows)
        for options in ({"limit": 0}, {"offset": -1}, {"statuses": ["bogus"]},
                        {"statuses": ["all", "open"]}, {"columns": ["missing"]}):
            with self.subTest(options=options), self.assertRaises(LedgerError):
                query_ledger(self.path, **options)
        for args in (("--limit", "0"), ("--offset", "-1"), ("--columns", "missing"),
                     ("--status", "all", "--status", "open")):
            with self.subTest(args=args):
                completed = self.cli(*args)
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, b"")


if __name__ == "__main__":
    unittest.main()
