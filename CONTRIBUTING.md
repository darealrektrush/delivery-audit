# Maintaining this candidate

Use synthetic examples in bug reports and tests. Record the Python version, commands, exit codes, expected and actual report, and smallest pair of records that reproduces a problem. Replace private IDs, credentials and payloads before sharing any sample.

Run the following from the source root:

```sh
python3 -m unittest -v
python3 delivery_audit.py delivery_audit_samples/github-deliveries.jsonl delivery_audit_samples/github-receipts.jsonl --expected-format github-delivery --observed-format github-receiver --format text
```

Use test cases for new behavior and preserve the original manifest schema, JSON report schema and exit-code contract unless introducing a documented breaking version. Use the repository issue tracker for public, synthetic reproductions and consult SECURITY.md for sensitive findings.
