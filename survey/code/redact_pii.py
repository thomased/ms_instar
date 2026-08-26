#!/usr/bin/env python3
"""Strip third-party email addresses out of the survey metadata.

For a subset of papers, `build_papers_from_pdfs.py` fell back to scraping
the PDF's front matter when structured metadata was unavailable. On
two-column layouts that pulls in whatever sat beside the title, which for
some journals includes the corresponding author's email, their funding
statement, and their affiliation, all interleaved into the `title` and
`abstract` fields.

Those emails belong to other researchers. They should not be republished
in a public data deposit, and they were never used by the analysis: the
scoring reads the extracted methods text in `texts/`, not these columns.
So they can be removed with no effect on any reported result.

This only removes the email addresses. It deliberately does not attempt
to repair the surrounding garbled text, which is a separate problem and
better fixed at the source by re-fetching metadata from Crossref.

Idempotent. Run from the survey/ directory:

    python3 code/redact_pii.py            # report what would change
    python3 code/redact_pii.py --write    # apply it
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TARGETS = {
    "results/papers.csv": ("title", "abstract"),
    "results/scores.csv": ("title",),
}
EMAIL = re.compile(r"[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}")
PLACEHOLDER = "[email removed]"


def redact(path: Path, columns: tuple[str, ...], write: bool) -> int:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    hits = 0
    for row in rows:
        for col in columns:
            if col not in row or not row[col]:
                continue
            cleaned, n = EMAIL.subn(PLACEHOLDER, row[col])
            if n:
                hits += n
                row[col] = re.sub(r"\s{2,}", " ", cleaned).strip()

    if hits and write:
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="apply the changes (default is a dry run)")
    args = ap.parse_args()

    total = 0
    for rel, columns in TARGETS.items():
        path = HERE / rel
        if not path.exists():
            print(f"  skip {rel} (not found)")
            continue
        n = redact(path, columns, args.write)
        total += n
        verb = "removed" if args.write else "would remove"
        print(f"  {rel}: {verb} {n} address{'es' if n != 1 else ''}")

    if total and not args.write:
        print("\nDry run. Re-run with --write to apply.")
    elif not total:
        print("\nNothing to redact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
