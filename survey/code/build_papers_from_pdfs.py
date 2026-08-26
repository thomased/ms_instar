#!/usr/bin/env python3
"""Build `results/papers.csv` from PDFs organised in per-journal
subfolders under `pdfs/`. Metadata (title, journal, DOI, abstract) is
harvested directly from PDF text — no network required, and folder
names can be whatever you like.

Detection order:
  1. DOI: scan page 1 text for `10.xxxx/yyyy`; that's authoritative.
  2. Journal: match page 1 text against a table of known journal
     header strings.  If none match, use the folder name.
  3. Title + abstract: parsed with a stack of publisher-family
     heuristics (Elsevier, Springer, Brill, Wiley, Oxford, RSS
     journals).

Just re-run whenever you drop new PDFs in.
"""
from __future__ import annotations
import csv
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("pip install pdfplumber")
try:
    import wordninja
except ImportError:
    wordninja = None

# Project root is one level up from this script's code/ folder.
HERE = Path(__file__).resolve().parent.parent
PDF_ROOT = HERE / "pdfs"
OUT = HERE / "results" / "papers.csv"

# ---- helpers ---------------------------------------------------------------
def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def sanitize(s: str) -> str:
    return re.sub(r"\s+", " ",
                  re.sub(r"[\x00-\x1f\x7f]", " ", s or "")).strip()


_KEEP_WORDS = {
    "analysis", "abstract", "however", "research", "control", "overall",
    "although", "original", "received", "published", "therefore",
    "significant", "measured", "reported", "observed", "different",
}


def fix_word_joins(text: str) -> str:
    """Insert spaces at plausible word boundaries in column-glued text
    from PDFs like Brill's JIFF."""
    if wordninja is None or not text:
        return text

    def _fix(tok: str) -> str:
        if len(tok) <= 7 or tok.lower() in _KEEP_WORDS:
            return tok
        if not re.match(r"^[A-Za-z]+$", tok):
            return tok
        parts = wordninja.split(tok)
        if len(parts) >= 2 and all(len(p) >= 2 for p in parts):
            if tok[0].isupper():
                parts[0] = parts[0].capitalize()
            return " ".join(parts)
        return tok

    return re.sub(r"[A-Za-z]{8,}", lambda m: _fix(m.group(0)), text)


def extract_page(pdf_path: Path, i: int = 0) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        if i >= len(pdf.pages):
            return ""
        return pdf.pages[i].extract_text() or ""


# ---- detection -------------------------------------------------------------
# Greedy match on non-whitespace after 10.xxxx/, then trim trailing junk.
_DOI_RE = re.compile(r"\b(10\.\d{4,}/\S+)")
_DOI_TRIM = ".,;)]}>|©"


# Elsevier journal-header patterns: "Journal Name V (YYYY) NNNNN"
# Maps to DOI 10.1016/j.<shorthand>.YYYY.NNNNN
_ELSEVIER_HEADER = re.compile(
    r"(Animal Behaviour|Journal of Invertebrate Pathology|"
    r"Journal of Insect Physiology|Aquaculture)\s+"
    r"\d+\s*\(\s*(\d{4})\s*\)\s+(\d+)"
)
_ELSEVIER_SHORT = {
    "Animal Behaviour": "anbehav",
    "Journal of Invertebrate Pathology": "jip",
    "Journal of Insect Physiology": "jinsphys",
    "Aquaculture": "aquaculture",
}


_DOI_INCOMPLETE = re.compile(
    r"^10\.\d+/(journal|s\d+|articles?|content|main|full)$",
    re.IGNORECASE,
)


def detect_doi(text: str, filename_stem: str) -> str:
    # Normalise line-wrapped DOIs before scanning, so e.g.
    # '10.1371/journal.\npbio.3003648' collapses to a single token.
    flat = re.sub(
        r"(10\.\d{4,}/[A-Za-z0-9._-]*)\s*[\r\n]\s*([A-Za-z0-9])",
        r"\1\2",
        text[:4000],
    )
    for m in _DOI_RE.finditer(flat):
        d = m.group(1)
        while d and d[-1] in _DOI_TRIM:
            d = d[:-1]
        if "/" not in d or len(d) < 9:
            continue
        # skip anything that looks like a truncated DOI prefix
        if _DOI_INCOMPLETE.match(d):
            continue
        return d
    # Elsevier header reconstruction
    m = _ELSEVIER_HEADER.search(text[:800])
    if m:
        short = _ELSEVIER_SHORT.get(m.group(1))
        if short:
            return f"10.1016/j.{short}.{m.group(2)}.{m.group(3)}"
    # filename fallback: '10-1093-beheco-araf123' → '10.1093/beheco/araf123'
    m = re.match(r"^(10)-(\d{4,})-(.+)$", filename_stem)
    if m:
        return f"{m.group(1)}.{m.group(2)}/" + m.group(3).replace("-", "/", 1)
    return ""


# Journal patterns: fragments to look for in page-1 text.
# First match wins; order more specific → more generic.
_JOURNAL_PATTERNS: list[tuple[str, list[str]]] = [
    ("Journal of Comparative Physiology A",
     ["Journal of Comparative Physiology A"]),
    ("Behavioral Ecology and Sociobiology",
     ["Behavioral Ecology and Sociobiology"]),
    ("Behavioral Ecology",
     ["academic.oup.com/beheco", "Behavioral Ecology"]),
    ("Journal of Insects as Food and Feed",
     ["Journal of Insects as Food and Feed", "brill.com/jiff"]),
    ("Aquaculture",
     ["Aquaculture Reports", "Aquaculture,", "www.elsevier.com/locate/aquaculture"]),
    ("Animal Behaviour",
     ["Animal Behaviour", "www.elsevier.com/locate/anbehav"]),
    ("Ethology",
     ["ETHOLOGY", "onlinelibrary.wiley.com/journal/eth"]),
    ("Journal of Experimental Biology",
     ["Journal of Experimental Biology", "jeb.biologists.org"]),
    ("Journal of Invertebrate Pathology",
     ["Journal of Invertebrate Pathology",
      "www.elsevier.com/locate/jip"]),
    ("Functional Ecology",
     ["Functional Ecology"]),
    ("Journal of Insect Physiology",
     ["Journal of Insect Physiology"]),
    ("The American Naturalist",
     ["The American Naturalist"]),
    ("Biology Letters",
     ["Biology Letters", "rsbl.royalsocietypublishing.org"]),
    ("Proceedings of the Royal Society B",
     ["Proceedings of the Royal Society B",
      "rspb.royalsocietypublishing.org"]),
    ("Royal Society Open Science",
     ["Royal Society Open Science", "rsos.royalsocietypublishing.org"]),
    ("Current Zoology", ["Current Zoology"]),
    ("Ecology Letters", ["Ecology Letters"]),
    ("Evolution", ["EVOLUTION\n", "evolution-journal"]),
    ("PLOS ONE", ["PLOS ONE", "journals.plos.org/plosone"]),
    ("PeerJ", ["PeerJ", "peerj.com"]),
]


# Nice display names when only the folder tells us what it is.
_FOLDER_FALLBACK: dict[str, str] = {
    "am_nat": "The American Naturalist",
    "an_beh": "Animal Behaviour",
    "anim_behav": "Animal Behaviour",
    "aquaculture": "Aquaculture",
    "acquaculture": "Aquaculture",  # user typo we forgive
    "be": "Behavioral Ecology",
    "bes": "Behavioral Ecology and Sociobiology",
    "biol_letters": "Biology Letters",
    "curr_zoo": "Current Zoology",
    "ecol_letters": "Ecology Letters",
    "ethology": "Ethology",
    "evolution": "Evolution",
    "fun_ecol": "Functional Ecology",
    "funct_ecol": "Functional Ecology",
    "j_comp_phys": "Journal of Comparative Physiology A",
    "j_exp_biol": "Journal of Experimental Biology",
    "jeb": "Journal of Experimental Biology",
    "j_insect_phys": "Journal of Insect Physiology",
    "jiff": "Journal of Insects as Food and Feed",
    "j_inv_parisit": "Journal of Invertebrate Pathology",
    "j_inv_pathol": "Journal of Invertebrate Pathology",
    "jip": "Journal of Invertebrate Pathology",
    "plos_biol": "PLOS Biology",
    "plos_one": "PLOS ONE",
    "peerj": "PeerJ",
    "proc_b": "Proceedings of the Royal Society B",
    "prsb": "Proceedings of the Royal Society B",
    "rsos": "Royal Society Open Science",
    "sci_reports": "Scientific Reports",
}


def detect_journal(text: str, folder: str) -> str:
    # Prefer folder-name mapping — user's organisation is authoritative.
    # Content-based detection is fallback for unmapped folder names.
    mapped = _FOLDER_FALLBACK.get(folder.lower())
    if mapped:
        return mapped
    head = text[:2500]
    for name, needles in _JOURNAL_PATTERNS:
        for n in needles:
            if n in head:
                return name
    return folder.replace("_", " ").title()


# ---- title + abstract parsers ---------------------------------------------
def _parse_springer_style(p1: str) -> tuple[str, str]:
    """Papers with a 'RESEARCH' banner and mid-dot author separator."""
    lines = [l.strip() for l in p1.split("\n") if l.strip()]
    start = 0
    for i, l in enumerate(lines):
        if l.upper() in ("RESEARCH", "REVIEW", "REVIEW ARTICLE",
                         "ORIGINAL ARTICLE"):
            start = i + 1
            break
    title_lines: list[str] = []
    j = start
    while j < len(lines):
        l = lines[j]
        if re.match(r"(Received|Revised|Accepted|Published|"
                    r"Communicated|©)", l):
            break
        if ("·" in l or "•" in l
                or re.search(r"[A-Z]\w+\s*\d+[,·]", l)):
            break
        title_lines.append(l)
        j += 1
    title = sanitize(" ".join(title_lines))
    abs_idx = p1.find("Abstract")
    abstract = ""
    if abs_idx != -1:
        tail = p1[abs_idx + len("Abstract"):]
        m = re.search(r"\b(Keywords|Introduction|Materials and methods|"
                      r"Methods)\b", tail)
        abstract = sanitize(tail[:m.start()] if m else tail[:1500])
    return title, abstract


def _parse_be_style(p1: str) -> tuple[str, str]:
    """Oxford Behavioral Ecology cover-page format."""
    dl = p1.find("Downloaded")
    head = p1[:dl].strip() if dl != -1 else p1
    lines = [l.strip() for l in head.split("\n") if l.strip()]
    author_idx = None
    for i in range(len(lines) - 1, -1, -1):
        l = lines[i]
        if ", " in l and not any(l.lower().startswith(w) for w in
                                  ("received", "published", "doi",
                                   "the", "in ", "we ", "of ", "by")):
            author_idx = i
            break
    if author_idx is None:
        author_idx = len(lines)
    return sanitize(" ".join(lines[:author_idx])), ""


def _parse_jiff_style(p1: str) -> tuple[str, str]:
    """Brill's column-glued layout."""
    lines = [l.strip() for l in p1.split("\n") if l.strip()]
    start = 0
    for i, l in enumerate(lines):
        if l.lower() in ("research article", "review article",
                         "short communication"):
            start = i + 1
            break
    title_lines: list[str] = []
    j = start
    while j < len(lines):
        l = lines[j]
        if (re.search(r"[A-Z]\.\s*[A-Z][a-z]*\s*\d", l)
                or re.search(r"\d+\s*(?:and|,)\s*[A-Z]", l)):
            break
        if re.match(r"(Received|Accepted|Abstract|\d+[A-Z])", l):
            break
        title_lines.append(l)
        j += 1
    title = fix_word_joins(sanitize(" ".join(title_lines)))
    abs_idx = p1.find("Abstract")
    abstract = ""
    if abs_idx != -1:
        tail = p1[abs_idx + len("Abstract"):]
        m = re.search(r"\n(Keywords|Introduction|Materials and methods|"
                      r"Methods|1\.\s+Introduction)\b", tail)
        abstract = fix_word_joins(sanitize(tail[:m.start()]
                                           if m else tail[:1500]))
    return title, abstract


_SKIP_HEADER_RE = re.compile(
    r"^(Contents lists available|ScienceDirect|"
    r"www\.|journal homepage|jou r na l|Journal homepage|"
    r"Received[:.]|Revised[:.]|Accepted[:.]|Published[:.]|"
    r"Available online|"
    r"Correspondence|E-mail:|A R T I C L E|"
    r"©|DOI[:.]|Editor:|Communicated by|"
    r"OPEN ACCESS|"
    r"RESEARCH ARTICLE|RESEARCH|RESEARCHARTICLE|R E S E A R C H|"
    r"REVIEW ARTICLE|REVIEW|"
    r"ORIGINAL ARTICLE|ORIGINAL RESEARCH|SHORT COMMUNICATION|"
    r"[0-9]+\s*of\s*[0-9]+$)"
)
# Structural author-line signals — much stricter than generic "capital
# words" so it doesn't false-fire on real titles.
_AUTHOR_SIGNAL_RE = re.compile(
    r"(\b[A-Z][a-z]+\s*\d+[,·]|"   # 'Smith1,' or 'Smith1·'
    r"\b[A-Z]\.\s*[A-Z]\.\s*[A-Z]|" # 'A. B. Cdefgh' initials chain
    r"\s\|\s[A-Z]|"                 # Wiley "First Last | First"
    r"\bet\s+al\.\s*\d)"            # 'et al.1'
)


def _parse_generic_landmarked(p1: str) -> tuple[str, str]:
    """A single generic parser driven by landmarks — 'RESEARCH ARTICLE' or
    similar as title-start; author line, 'Received:', 'Abstract' or
    'ABSTRACT' or 'A B S T R A C T' as title-end and abstract-start.
    Works across Elsevier, Wiley, Springer, JEB, RS journals, PLoS."""
    lines = [l.strip() for l in p1.split("\n") if l.strip()]

    # 1. Find title start: skip header noise
    start = 0
    for i, l in enumerate(lines[:20]):
        if _SKIP_HEADER_RE.match(l):
            start = i + 1
    # Extra skip: journal name line without other content
    while start < len(lines) and (
            len(lines[start]) < 3 or
            _SKIP_HEADER_RE.match(lines[start])):
        start += 1

    # 2. Collect title lines until author-like line, affiliation,
    #    "Received:", "Abstract", "Correspondence", or a line that's
    #    clearly authorship (contains "|" between names, or digit
    #    superscripts).
    title_lines: list[str] = []
    end_markers = re.compile(
        r"^(Received|Revised|Accepted|Published|Communicated|"
        r"Correspondence|Editor:|Keywords|Abstract|ABSTRACT|"
        r"A B S T R A C T|Article history)")
    for l in lines[start:start + 10]:
        if end_markers.match(l):
            break
        if "·" in l or "•" in l:  # mid-dot author separator (Springer)
            break
        if _AUTHOR_SIGNAL_RE.search(l):
            break
        if len(l) < 3:
            continue
        title_lines.append(l)
    title = sanitize(" ".join(title_lines))

    # 3. Abstract: search for common markers
    abs_idx = -1
    for marker in ("A B S T R A C T", "ABSTRACT", "Abstract"):
        j = p1.find(marker)
        if j != -1 and (abs_idx == -1 or j < abs_idx):
            abs_idx = j
            abs_len = len(marker)
    abstract = ""
    if abs_idx != -1:
        tail = p1[abs_idx + abs_len:]
        m = re.search(
            r"\b(KEYWORDS|Keywords|Introduction|"
            r"1\.\s+Introduction|Materials and methods|Methods|"
            r"MATERIALS AND METHODS|1\s*\|\s*INTRODUCTION|"
            r"2\s*\|\s*)", tail)
        abstract = sanitize(tail[:m.start()] if m else tail[:2000])
    return title, abstract


def _parse_jeb_style(p1: str) -> tuple[str, str]:
    """JEB — front matter is column-glued but the title afterwards is
    spaced. Anchor on 'RESEARCHARTICLE' (no space) or 'RESEARCH ARTICLE'."""
    for marker in ("RESEARCHARTICLE", "RESEARCH ARTICLE"):
        j = p1.find(marker)
        if j != -1:
            after = p1[j + len(marker):]
            # take everything up to author line (initials + surname
            # pattern, all glued)
            lines = [l.strip() for l in after.split("\n") if l.strip()]
            title_lines: list[str] = []
            for l in lines[:6]:
                # author line often starts with initials.surname
                if re.match(r"^[A-Z][a-z]*[A-Z]?\.[A-Z]\.", l):
                    break
                if re.match(r"^ABSTRACT|^Abstract", l):
                    break
                title_lines.append(l)
            title = sanitize(" ".join(title_lines))
            # Abstract detection
            abs_idx = p1.find("ABSTRACT", j)
            if abs_idx == -1:
                abs_idx = p1.find("Abstract", j)
            abstract = ""
            if abs_idx != -1:
                tail = p1[abs_idx + len("ABSTRACT"):]
                m = re.search(r"\n(KEYWORDS|Keywords|Introduction|"
                              r"1\.\s+|INTRODUCTION|MATERIALS)", tail)
                abstract = fix_word_joins(sanitize(
                    tail[:m.start()] if m else tail[:2000]))
            return title, abstract
    return _parse_generic_landmarked(p1)


def _parse_generic(p1: str) -> tuple[str, str]:
    lines = [l.strip() for l in p1.split("\n") if l.strip()]
    title = sanitize(" ".join(lines[:3]))
    abs_idx = p1.find("Abstract")
    abstract = ""
    if abs_idx != -1:
        tail = p1[abs_idx + len("Abstract"):]
        m = re.search(r"\b(Keywords|Introduction|Methods)\b", tail)
        abstract = sanitize(tail[:m.start()] if m else tail[:1500])
    return title, abstract


# Route to a parser based on detected journal
def route_parser(journal: str):
    j = journal.lower()
    if "comparative physiology" in j or "sociobiology" in j:
        return _parse_springer_style
    if "behavioral ecology" in j and "sociobiology" not in j:
        return _parse_be_style
    if "insects as food" in j:
        return _parse_jiff_style
    if "experimental biology" in j:
        return _parse_jeb_style
    return _parse_generic_landmarked


# ---- main -----------------------------------------------------------------
def main() -> None:
    rows: list[dict] = []
    for folder_dir in sorted(PDF_ROOT.iterdir()):
        if not folder_dir.is_dir():
            continue
        for pdf in sorted(folder_dir.iterdir()):
            if pdf.suffix.lower() != ".pdf":
                continue
            try:
                p1 = extract_page(pdf, 0)
            except Exception as e:
                print(f"! read failed for {pdf.name}: {e}",
                      file=sys.stderr)
                continue
            journal = detect_journal(p1, folder_dir.name)
            doi = detect_doi(p1, pdf.stem)
            parser = route_parser(journal)
            try:
                title, abstract = parser(p1)
            except Exception as e:
                print(f"! parse failed for {pdf.name}: {e}",
                      file=sys.stderr)
                title, abstract = "", ""
            slug = slugify(doi) if doi else slugify(
                f"{folder_dir.name}-{pdf.stem}"
            )
            rows.append({
                "slug": slug,
                "doi": doi,
                "journal": journal,
                "title": title,
                "abstract": abstract,
                "publication_date": "",
                "oa_status": "",
                "pdf_url": "",
                "openalex_id": "",
                "pdf_path": str(pdf.relative_to(PDF_ROOT.parent)),
            })

    if not rows:
        sys.exit("no PDFs found")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()),
                           quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"wrote {len(rows)} rows to {OUT.relative_to(HERE)}\n")
    by_j: dict[str, int] = {}
    for r in rows:
        by_j[r["journal"]] = by_j.get(r["journal"], 0) + 1
    for j, n in sorted(by_j.items(), key=lambda x: -x[1]):
        print(f"  {n:3d}  {j}")


if __name__ == "__main__":
    main()
