# Preserving input evidence

The README's jq recipe targets previously validated, single-object GitHub exports. JSON parsers can discard duplicate keys during compaction, and numeric behavior differs among serializers and builds. Delivery Audit checks the JSONL bytes it receives. It cannot reconstruct duplicate keys or precision lost upstream. Preserve raw exports locally and use the same serialization rules on both sides. If wire-level equality is your question, compute SHA-256 over the original bytes on each side and use manifest mode. A wire-level comparison treats changes in spacing or key order as a difference.

For raw single-object source files, the following offline recipe checks duplicate keys before compaction and uses the installed candidate's exact decimal representation. Run from the source checkout with Python 3.12+. Pass file paths from only one source at a time and use a new output file per run.

```sh
python3 - sender-details/*.json > sender.jsonl <<'PYTHON'
from decimal import Decimal
from pathlib import Path
import json
import sys
from delivery_audit import MAX_LINE_BYTES, canonical_json, reject_constant, unique_keys

rows = []
for name in sys.argv[1:]:
    with Path(name).open("rb") as stream:
        raw = stream.read(MAX_LINE_BYTES + 1)
    if len(raw) > MAX_LINE_BYTES:
        raise SystemExit(f"Input file exceeds 8 MiB: {name}")
    record = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_keys,
                        parse_int=Decimal, parse_float=Decimal, parse_constant=reject_constant)
    request = record["request"]
    header = {k: v for k, v in request["headers"].items() if k.lower() == "x-github-delivery"}
    rows.append(canonical_json({"guid": record["guid"], "request": {"headers": header, "payload": request["payload"]}}))
for row in rows:
    print(row)
PYTHON
```

For receiver exports, use the same strict parser against saved records with 'headers' and 'body'. Emit only those two fields and retain the incoming delivery header. Work with a bounded set of files and check successful conversion before treating a file as an empty window. All examples in this candidate use synthetic IDs.
