# Delivery Audit

Find out which webhook deliveries reached your receiver. Compare a sender export with a receiver log and get a sorted list of missing IDs, unexpected IDs and changed payloads. Identical retries have their own count. Runs offline with Python 3.12 or newer and the standard library.

## Try a delivery failure

Install the wheel from its containing directory in an isolated environment. The wheel includes the sample data.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps ./rektrush_delivery_audit-0.2.0rc2-py3-none-any.whl
.venv/bin/delivery-audit --demo clean --format text
.venv/bin/delivery-audit --demo drift --format text
```

On Windows use `.venv\Scripts\python.exe` and `.venv\Scripts\delivery-audit.exe`. From a source checkout you can also run `python3 delivery_audit.py --demo drift --format text` immediately.

The clean demo exits 0 and reports two matched IDs. One delivery reached the receiver twice with identical content. The drift demo exits 1 and prints:

```text
Matched IDs: 0
Missing: 1
  Check the capture window and receiver logs: "demo-issue-2"
Unexpected: 1
  Check sender scope and retention: "demo-push-3"
Conflicts: 1
  Inspect source records sharing the same delivery ID: "demo-push-1"
IDs with identical retries: 0
```

## Compare a real GitHub receiver

Choose one webhook and a settled time window. Gather the repository webhook **delivery details** for the sender and matching receiver records. A list of delivery summaries lacks the request payload. On the receiver side, use records from after your application's normal signature check containing the incoming delivery header and the parsed JSON body. Delivery Audit reads local files.

If you have one saved JSON object per file, compact them into JSON Lines with this local shell recipe. Use separate source directories. Each receiver object must already match the shape below.

```sh
jq -c '{guid,request:{headers:(.request.headers | with_entries(select(.key | ascii_downcase == "x-github-delivery"))),payload:.request.payload}}' sender-details/*.json > sender.jsonl
jq -c '{headers:(.headers | with_entries(select(.key | ascii_downcase == "x-github-delivery"))),body}' receiver-records/*.json > receiver.jsonl
```

Supply one UTF-8 JSON object per physical line. Example receiver record:

```json
{"headers":{"x-github-delivery":"demo-issue-2"},"body":{"action":"opened","issue":{"number":7}}}
```

Run the comparison with matching source formats:

```sh
.venv/bin/delivery-audit sender.jsonl receiver.jsonl --expected-format github-delivery --observed-format github-receiver --format text
```

Keep raw exports private. A log that lacks comparable IDs or bodies needs an exporter before content equality can be evaluated. Values can reveal confidential information even when a delivery body looks routine. Standard output includes IDs and counts. Use synthetic or pseudonymous IDs for shared reports.

## General digest manifests

If both services already export the same content digest, supply two files with rows like this one. The SHA-256 field uses 64 lowercase hexadecimal characters. For example, this row represents an empty byte string:

```json
{"event_id":"example-01","sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
```

```sh
.venv/bin/delivery-audit expected.jsonl observed.jsonl
```

Source checkout examples live in `examples/` for manifests and `delivery_audit_samples/` for GitHub records. Select `--format text` for an operator report. JSON schema version 1 is the default.

## Interpret a result

| Result | Meaning | First investigation |
| --- | --- | --- |
| matched | Both sides have the same single digest | Record the count for that window. |
| missing | Only the sender has this event ID | Check window boundaries and receiver retention. |
| unexpected | Only the receiver has this ID | Check publisher scope and sender retention. |
| conflicts | A shared ID has different content, or either side gives the same ID multiple digests | Inspect the records and ensure both exporters hash comparable content. |
| repeats | Identical ID and digest recorded more than once, counted separately per side | Check retry handling if downstream work was duplicated. |

Each ID falls in one of the first four groups. Repeats may overlap any group. Exit 0 means the supplied event identities matched, including repeated-only differences. Exit 1 means an audit difference. Exit 2 means invalid inputs or usage. A missing ID alone does not establish delivery failure. Avoid automatically replaying an event from this result.

## Input and output details

Event IDs are case-sensitive. Both sides must share an identifier namespace. The GitHub adapters require a single case-insensitive X-GitHub-Delivery header. The sender's guid must equal that header. Unrelated headers and plain response metadata are ignored. Both adapters hash parsed JSON objects. Object order, whitespace and equivalent decimal spellings compare equal. Array order and string values are significant. Duplicate JSON keys and non-finite numbers are rejected.

The local digest encoding sorts keys by Unicode code point and uses Python ASCII JSON strings. Numbers use a signed coefficient without trailing zeroes followed by e and its base-10 exponent. All zero representations become 0. GitHub adapters should normally be paired together. A raw HTTP body hash may differ. A digest comparison cannot authenticate an incoming HTTP request or establish side effects at the receiver.

Rows may use up to 8 MiB including a terminating newline. Memory grows with distinct ID and digest pairs. Split large datasets into consistently scoped windows. SHA-256 digests of predictable content can be guessed. Keep logs and reports local, and prefer minimal synthetic reproductions when asking for help.

## Development

Run `python3 -m unittest -v` from the source root. The core reader validates one bounded line at a time, hashes or accepts a digest, and counts occurrences per ID and digest. The comparison joins these keys, assigns each identity a status and emits deterministic output.

Build locally with a PEP 517 build frontend and setuptools 77 or newer. There are no third-party runtime dependencies. The distribution name is `rektrush-delivery-audit`. The installed command is `delivery-audit`. Contributor guidance and the MIT license are included in the source distribution.

[GitHub delivery-detail schema](https://docs.github.com/en/rest/repos/webhooks#get-a-delivery-for-a-repository-webhook) · [GitHub delivery headers](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
