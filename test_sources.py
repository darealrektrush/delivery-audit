from pathlib import Path
import itertools
import json
import tempfile
import unittest

from delivery_audit import compare, read_manifest, text_report, MAX_LINE_BYTES


class SourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name, "log.jsonl")

    def parse(self, obj, source):
        self.path.write_text(json.dumps(obj), encoding="utf-8")
        return read_manifest(self.path, source)

    def receiver(self, body):
        return {"headers": {"x-github-delivery": "event-1"}, "body": body}

    def sender(self, body):
        return {"guid": "event-1", "request": {"headers": {"X-GitHub-Delivery": "event-1"},
                                              "payload": body}, "duration": 0.23}

    def test_different_envelopes_same_logical_event(self):
        payload = {"one": "☃", "two": ["0", None, False, True]}
        expected = self.parse(self.sender(payload), "github-delivery")
        for keys in itertools.permutations(payload):
            row = self.receiver({key: payload[key] for key in keys})
            result = compare(expected, self.parse(row, "github-receiver"))
            self.assertEqual(result["matched"], 1)

    def test_exact_decimal(self):
        def numeric(literal):
            row = json.dumps(self.receiver({"value": "replace"})).replace('"replace"', literal)
            self.path.write_text(row)
            return read_manifest(self.path, "github-receiver")
        self.assertEqual(numeric("100.000"), numeric("1e2"))
        self.assertEqual(numeric("-0.0"), numeric("0"))
        self.assertNotEqual(numeric("1.00000000000000000001"), numeric("1.00000000000000000002"))
        self.assertNotEqual(numeric("1"), numeric('"1"'))
        self.assertNotEqual(numeric("1"), numeric("true"))

    def test_missing_header_ambiguous_header_and_mismatched_guid(self):
        for headers in [{}, {"x-github-delivery": "event-1", "X-GitHub-Delivery": "event-2"},
                        {"x-github-delivery": "other"}, {"x-github-delivery": []}, None]:
            row = self.sender({})
            row["request"]["headers"] = headers
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                self.parse(row, "github-delivery")

    def test_incomplete_and_raw_payloads(self):
        for row, source in [({"guid": "event-1"}, "github-delivery"),
                            (self.receiver("{}"), "github-receiver"),
                            (self.receiver(None), "github-receiver"),
                            (self.receiver([]), "github-receiver")]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.parse(row, source)

    def test_ignore_unrelated_headers_and_retain_array_order(self):
        row = self.sender({"values": [1, 2]})
        row["request"]["headers"]["X-Hub-Signature-256"] = "synthetic-value"
        expected = self.parse(row, "github-delivery")
        observed = self.parse(self.receiver({"values": [2, 1]}), "github-receiver")
        result = compare(expected, observed)
        self.assertEqual(result["conflicts"], ["event-1"])
        self.assertNotIn("synthetic-value", text_report(result))

    def test_nonfinite_and_oversize_fail_with_location(self):
        for raw in (json.dumps(self.receiver({"x": float("nan")})).encode(),
                    b" " * (MAX_LINE_BYTES + 1)):
            self.path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "line 1"):
                read_manifest(self.path, "github-receiver")

    def test_text_escapes_control_characters(self):
        result = compare({"x\nY": {}}, {})
        output = text_report({**result, "missing": ["x\nY"]})
        self.assertIn('"x\\nY"', output)
        self.assertNotIn("x\nY", output)
