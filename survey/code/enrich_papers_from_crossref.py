#!/usr/bin/env python3
"""Enrich `results/papers.csv` with authoritative metadata from CrossRef
for any row that has a DOI. Overwrites the title, journal, abstract,
and publication_date columns when CrossRef returns a value; leaves the
row alone when it doesn't. Rows without a DOI are untouched.

Run this after `build_papers_from_pdfs.py`. Idempotent — safe to
re-run whenever you add more PDFs.

Requires internet (CrossRef API, no key needed).
Requires: requests
"""
from __future__ import annotations
import csv
import os
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

# Project root is one level up from this script's code/ folder.
HERE = Path(__file__).resolve().parent.parent
CSV_PATH = HERE / "results" / "papers.csv"
_CONTACT = os.environ.get("SURVEY_CONTACT_EMAIL", "").strip()
USER_AGENT = (f"instar-survey/0.1 (mailto:{_CONTACT})" if _CONTACT
              else "instar-survey/0.1")


def fetch(doi: str) -> dict | None:
    url = f"https://api.crossref.org/works/{doi}"
    try:
        r = requests.get(url,
                         headers={"User-Agent": USER_AGENT,
                                  "Accept": "application/json"},
                         timeout=20)
    except requests.RequestException as e:
        print(f"  ! {doi}: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  ! {doi}: HTTP {r.status_code}", file=sys.stderr)
        return None
    return r.json().get("message")


def pick_date(msg: dict) -> str:
    for key in ("published-print", "published-online", "published",
                "issued"):
        d = msg.get(key)
        if d and d.get("date-parts"):
            dp = d["date-parts"][0]
            return "-".join(str(x).zfill(2) for x in dp)
    return ""


def strip_jats(s: str) -> str:
    # CrossRef abstracts sometimes come with JATS tags
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def main() -> None:
    if not CSV_PATH.exists():
        sys.exit(f"missing {CSV_PATH}")

    with CSV_PATH.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("empty papers.csv")

    n_hit = n_miss = n_skip = 0
    for r in rows:
        doi = (r.get("doi") or "").strip()
        if not doi:
            n_skip += 1
            continue
        print(f"fetching {doi} ...", flush=True)
        msg = fetch(doi)
        if not msg:
            n_miss += 1
            continue
        title = (msg.get("title") or [""])[0]
        journal = (msg.get("container-title") or [""])[0]
        abstract = strip_jats(msg.get("abstract") or "")
        pubdate = pick_date(msg)
        if title:
            r["title"] = title
        if journal:
            r["journal"] = journal
        if abstract:
            r["abstract"] = abstract
        if pubdate:
            r["publication_date"] = pubdate
        n_hit += 1
        time.sleep(0.15)  # polite

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()),
                           quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"\nenriched: {n_hit}  missed: {n_miss}  skipped (no DOI): {n_skip}")


if __name__ == "__main__":
    main()
