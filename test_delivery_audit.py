import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from delivery_audit import compare, read_manifest

ROOT = Path(__file__).resolve().parent
A = "a" * 64
B = "b" * 64


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "rows"

    def load(self, rows):
        self.path.write_text("".join(json.dumps(dict(event_id=k, sha256=v)) + "\n" for k, v in rows))
        return read_manifest(self.path)

    def test_reordered_and_identical_retries(self):
        original = self.load([("x", A), ("y", B)])
        snapshots = [compare(original, self.load(rows)) for rows in itertools.permutations(
            [("x", A), ("y", B), ("x", A)])]
        self.assertTrue(all(result == snapshots[0] for result in snapshots))
        self.assertEqual(snapshots[0]["matched"], 2)
        self.assertEqual(snapshots[0]["repeats"], [dict(event_id="x", expected=0, observed=1)])

    def test_diff_categories_and_sort(self):
        report = compare(self.load([("z", B), ("a", A), ("x", B)]), self.load([("w", A), ("x", A)]))
        self.assertEqual((report["missing"], report["unexpected"], report["conflicts"]),
                         (["a", "z"], ["w"], ["x"]))

    def test_conflicts_within_either_side(self):
        bad = self.load([("x", A), ("x", B), ("x", B)])
        for result in (compare(bad, {}), compare({}, bad), compare(bad, bad)):
            self.assertEqual(result["conflicts"], ["x"])
            self.assertEqual(result["missing"] + result["unexpected"], [])
        self.assertEqual(compare(bad, {})["repeats"][0]["expected"], 1)

    def test_reject_invalid_rows_with_location(self):
        row = json.dumps(dict(event_id="x", sha256=A))
        for invalid in [b"", b"null", b"{", b"[]", b"\xff", b"{}",
                        b'{"event_id":"a","event_id":"b","sha256":"x"}',
                        row.replace('"x"', '"  "').encode(), row.replace(A, A.upper()).encode(),
                        row.replace('"event_id"', '"id"').encode()]:
            with self.subTest(invalid=invalid):
                self.path.write_bytes(row.encode() + b"\n" + invalid + b"\n")
                with self.assertRaisesRegex(ValueError, "line 2"):
                    read_manifest(self.path)

    def test_empty_and_distinct_ids(self):
        self.assertEqual(compare(self.load([]), {})["matched"], 0)
        self.assertEqual(compare(self.load([("x", A)]), self.load([("X", A)]))["missing"], ["x"])

    def test_cli(self):
        expected = ROOT / "examples" / "expected.jsonl"
        for name, status in [("reordered.jsonl", 0), ("drift.jsonl", 1), ("absent.jsonl", 2)]:
            process = subprocess.run([sys.executable, str(ROOT / "delivery_audit.py"), str(expected),
                                      str(expected.with_name(name))], capture_output=True, text=True)
            self.assertEqual(process.returncode, status)
            if status == 2:
                self.assertEqual(process.stdout, "")
                self.assertTrue(process.stderr)
            else:
                self.assertEqual(json.loads(process.stdout)["schema_version"], 1)
                self.assertEqual(process.stderr, "")


if __name__ == "__main__":
    unittest.main()
