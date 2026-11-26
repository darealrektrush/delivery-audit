from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import unittest

from delivery_audit import main


class DemoTests(unittest.TestCase):
    def run_demo(self, *args):
        output = StringIO()
        with redirect_stdout(output):
            status = main(list(args))
        return status, output.getvalue()

    def test_clean_packaged_inputs(self):
        status, out = self.run_demo("--demo", "clean")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)["matched"], 2)
        self.assertEqual(json.loads(out)["repeats"], [{"event_id": "demo-issue-2", "expected": 0, "observed": 1}])

    def test_drift_packaged_inputs(self):
        status, out = self.run_demo("--demo", "drift", "--format", "text")
        self.assertEqual(status, 1)
        self.assertIn("Missing: 1", out)
        self.assertIn("demo-push-1", out)

    def test_reject_ambiguous_file_inputs(self):
        with redirect_stderr(StringIO()):
            for args in ([], ["only-one"], ["a", "b", "--demo", "clean"],
                         ["--demo", "drift", "--expected-format", "github-delivery"]):
                with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                    main(args)
                self.assertEqual(error.exception.code, 2)
