"""Compare expected events with receiver logs from GitHub or precomputed digest manifests."""
import argparse
from collections import Counter
from contextlib import ExitStack
from decimal import Decimal, InvalidOperation
from importlib.resources import as_file, files
import hashlib
import json
from pathlib import Path
import re
import sys

VERSION = "0.2.0rc2"
MAX_LINE_BYTES = 8 * 1024 * 1024
SOURCES = ("manifest", "github-delivery", "github-receiver")
DIGEST = re.compile(r"[0-9a-f]{64}")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def canonical_json(value):
    """Encode sorted JSON with exact, normalized JSON numbers for GitHub adapters."""
    if isinstance(value, Decimal):
        if not value:
            return "0"
        sign, digits, exponent = value.as_tuple()
        coefficient = "".join(map(str, digits)).rstrip("0")
        exponent += len(digits) - len(coefficient)
        return ("-" if sign else "") + coefficient + "e" + str(exponent)
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        entries = (json.dumps(key) + ":" + canonical_json(value[key]) for key in sorted(value))
        return "{" + ",".join(entries) + "}"
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def delivery_id(headers):
    if not isinstance(headers, dict):
        raise ValueError("expected HTTP headers as an object")
    values = [v for k, v in headers.items() if k.lower() == "x-github-delivery"]
    if len(values) != 1:
        raise ValueError("expected exactly one X-GitHub-Delivery header")
    return values[0]


def event_record(row, source):
    if not isinstance(row, dict):
        raise ValueError("expected a JSON object")
    if source == "manifest":
        if set(row) != {"event_id", "sha256"}:
            raise ValueError("expected event_id and sha256")
        event_id, digest = row["event_id"], row["sha256"]
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError("sha256 must contain 64 lowercase hexadecimal digits")
    else:
        request = row.get("request") if source == "github-delivery" else row
        if not isinstance(request, dict):
            raise ValueError("expected a delivery detail with request.headers and request.payload")
        event_id = delivery_id(request.get("headers"))
        if source == "github-delivery" and row.get("guid") != event_id:
            raise ValueError("guid and X-GitHub-Delivery must match")
        payload = request.get("payload" if source == "github-delivery" else "body")
        if not isinstance(payload, dict):
            raise ValueError("expected a parsed JSON object payload")
        digest = hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id must be a nonblank string")
    return event_id, digest


def reject_constant(_):
    raise ValueError("non-finite value is invalid JSON")


def read_manifest(path, source="manifest"):
    """Read one bounded UTF-8 JSON object per physical line."""
    if source not in SOURCES:
        raise ValueError("unknown source format")
    events = {}
    with path.open("rb") as stream:
        number = 0
        while raw := stream.readline(MAX_LINE_BYTES + 1):
            number += 1
            try:
                if len(raw) > MAX_LINE_BYTES:
                    raise ValueError("line exceeds 8 MiB")
                row = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_keys,
                                 parse_int=Decimal, parse_float=Decimal, parse_constant=reject_constant)
                event_id, digest = event_record(row, source)
            except (ValueError, RecursionError, InvalidOperation) as exc:
                raise ValueError(f"{path}, line {number}: {exc}") from exc
            events.setdefault(event_id, Counter())[digest] += 1
    return events


def compare(expected, observed):
    """Classify identities across both manifests and track literal retries separately."""
    matched = 0
    missing, unexpected, conflicts, repeats = [], [], [], []
    for event_id in sorted(expected.keys() | observed.keys()):
        before = expected.get(event_id, {})
        after = observed.get(event_id, {})
        if len(before) > 1 or len(after) > 1 or (before and after and before.keys() != after.keys()):
            conflicts.append(event_id)
        elif not before:
            unexpected.append(event_id)
        elif not after:
            missing.append(event_id)
        else:
            matched += 1
        expected_repeats = sum(before.values()) - len(before)
        observed_repeats = sum(after.values()) - len(after)
        if expected_repeats or observed_repeats:
            repeats.append(dict(event_id=event_id, expected=expected_repeats, observed=observed_repeats))
    return dict(schema_version=1, matched=matched, missing=missing, unexpected=unexpected,
                conflicts=conflicts, repeats=repeats)


def text_report(result):
    rows = [f"Matched IDs: {result['matched']}"]
    actions = {
        "missing": "Check the capture window and receiver logs",
        "unexpected": "Check sender scope and retention",
        "conflicts": "Inspect source records sharing the same delivery ID",
    }
    for key, action in actions.items():
        ids = result[key]
        rows.append(f"{key.capitalize()}: {len(ids)}")
        if ids:
            rows.append("  " + action + ": " + ", ".join(json.dumps(event_id) for event_id in ids))
    rows.append(f"IDs with identical retries: {len(result['repeats'])}")
    for item in result["repeats"]:
        rows.append(f"  {json.dumps(item['event_id'])}  expected={item['expected']}  observed={item['observed']}")
    return "\n".join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path, nargs="?", help="sender JSONL export")
    parser.add_argument("observed", type=Path, nargs="?", help="receiver JSONL export")
    parser.add_argument("--expected-format", choices=SOURCES, default="manifest")
    parser.add_argument("--observed-format", choices=SOURCES, default="manifest")
    parser.add_argument("--format", choices=("json", "text"), default="json", help="output format")
    parser.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    parser.add_argument("--demo", choices=("clean", "drift"),
                        help="run the bundled GitHub example without input files")
    args = parser.parse_args(argv)
    if args.demo:
        if args.expected or args.observed or (args.expected_format, args.observed_format) != ("manifest", "manifest"):
            parser.error("--demo chooses its own inputs and input formats")
    elif not args.expected or not args.observed:
        parser.error("supply both input files or choose --demo clean or --demo drift")
    try:
        with ExitStack() as stack:
            if args.demo:
                samples = files("delivery_audit_samples")
                name = "github-receipts.jsonl" if args.demo == "clean" else "github-drift.jsonl"
                args.expected = stack.enter_context(as_file(samples.joinpath("github-deliveries.jsonl")))
                args.observed = stack.enter_context(as_file(samples.joinpath(name)))
                args.expected_format, args.observed_format = "github-delivery", "github-receiver"
            result = compare(read_manifest(args.expected, args.expected_format),
                             read_manifest(args.observed, args.observed_format))
    except (ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.format == "json" else text_report(result))
    return int(any(result[key] for key in ("missing", "unexpected", "conflicts")))


if __name__ == "__main__":
    sys.exit(main())
